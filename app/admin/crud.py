"""
Generic add / edit / delete / toggle handler used by almost every admin page.

A page is described declaratively (which model, which fields, which uploads) instead of
repeating ~100 lines of request handling per page. All input is validated here:
bad numbers never crash, links can't be `javascript:`, uploads are content-checked.
"""
import re
from dataclasses import dataclass, field as dc_field
from typing import Callable, Optional, Sequence

from flask import current_app, flash
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..services.uploads import clean_path_input, remove_unreferenced, save_upload
from ..utils import form_str, safe_url, to_int

_POS_RE = re.compile(r"^[A-Za-z0-9 %.\-]{1,40}$")


@dataclass
class Field:
    name: str                      # model attribute AND form field name
    kind: str = "str"              # str | int | bool | link | path | pos
    required: bool = False
    default: object = None         # used when blank on add (and for optional blank on edit)
    keep_if_blank: bool = False    # on edit: blank input keeps the current value
    label: Optional[str] = None


@dataclass
class FileField:
    form_file: str                 # <input type=file name=...>
    form_path: str                 # <input type=text name=...> (existing path / URL)
    attr: str                      # model attribute that stores the path
    kind: str                      # image | pdf
    subdir: str                    # folder inside static/uploads
    prefix: str = ""
    clear_on_blank: bool = False   # edit: blank path text clears the value (PDF, thumbnail)


@dataclass
class Crud:
    model: type
    label: str
    fields: Sequence[Field]
    files: Sequence[FileField] = ()
    edit_action: str = "edit"
    allow: Sequence[str] = ("add", "edit", "delete", "toggle")
    required_files: Sequence[str] = ()          # attrs that must end up non-empty on add
    after_fill: Optional[Callable] = None       # hook(item, form, mode)
    add_defaults: Optional[Callable] = None     # hook() -> dict of extra attribute defaults
    order_by: Optional[Callable] = None
    msgs: dict = dc_field(default_factory=dict)

    # ---------------------------------------------------------------- helpers
    def _msg(self, key, fallback):
        return self.msgs.get(key, fallback)

    def _value_for_add(self, f, form):
        if f.kind == "bool":
            return bool(form.get(f.name))
        if f.kind == "int":
            return to_int(form.get(f.name), 0)
        raw = form_str(form, f.name)
        if f.kind == "link":
            raw = safe_url(raw)
        elif f.kind == "path":
            raw = clean_path_input(raw)
        elif f.kind == "pos":
            raw = raw if _POS_RE.match(raw) else ""
        return raw or f.default

    def _value_for_edit(self, f, form, current):
        if f.kind == "bool":
            return bool(form.get(f.name))
        if f.name not in form:
            return current                       # field not on this form: leave untouched
        if f.kind == "int":
            return to_int(form.get(f.name), current if isinstance(current, int) else 0)
        raw = form_str(form, f.name)
        if f.kind == "link":
            raw = safe_url(raw)
        elif f.kind == "path":
            raw = clean_path_input(raw)
        elif f.kind == "pos":
            raw = raw if _POS_RE.match(raw) else ""
        if not raw and (f.required or f.keep_if_blank):
            return current
        return raw or f.default

    def _find(self, form):
        item_id = to_int(form.get("id"), None)
        item = db.session.get(self.model, item_id) if item_id is not None else None
        if item is None:
            flash("That item no longer exists.", "warning")
        return item

    def _apply_files(self, item, form, files, mode):
        """Handle uploads / typed paths. Returns list of replaced (now unused) paths."""
        replaced = []
        for ff in self.files:
            path, err = save_upload(files.get(ff.form_file), ff.subdir, ff.kind, ff.prefix)
            if err:
                flash(err, "danger")
            old = getattr(item, ff.attr, None)
            if path:
                setattr(item, ff.attr, path)
                if mode == "edit" and old:
                    replaced.append(old)
            elif mode == "add":
                setattr(item, ff.attr, clean_path_input(form.get(ff.form_path, "")) or None)
            elif ff.form_path in form:
                typed = clean_path_input(form.get(ff.form_path, ""))
                if typed:
                    setattr(item, ff.attr, typed)
                elif ff.clear_on_blank:
                    setattr(item, ff.attr, None)
                if old and getattr(item, ff.attr, None) != old:
                    replaced.append(old)
        return replaced

    # ---------------------------------------------------------------- actions
    def add(self, form, files, **extra):
        values = {}
        for f in self.fields:
            if f.required and f.kind not in ("bool", "int") and not form_str(form, f.name):
                flash(f"{f.label or f.name.replace('_', ' ').title()} is required.", "danger")
                return False
            values[f.name] = self._value_for_add(f, form)
        if self.add_defaults:
            for k, v in self.add_defaults().items():
                if not values.get(k):
                    values[k] = v
        values.update(extra)
        if hasattr(self.model, "is_active"):
            values.setdefault("is_active", True)
        item = self.model(**values)
        self._apply_files(item, form, files, "add")
        for attr in self.required_files:
            if not getattr(item, attr, None):
                flash("Please upload an image or provide an image path.", "danger")
                return False
        if self.after_fill:
            self.after_fill(item, form, "add")
        db.session.add(item)
        db.session.commit()
        flash(self._msg("add", f"{self.label} added."), "success")
        return True

    def edit(self, form, files):
        item = self._find(form)
        if item is None:
            return False
        for f in self.fields:
            setattr(item, f.name, self._value_for_edit(f, form, getattr(item, f.name, None)))
        replaced = self._apply_files(item, form, files, "edit")
        if self.after_fill:
            self.after_fill(item, form, "edit")
        db.session.commit()
        remove_unreferenced(replaced)
        flash(self._msg("edit", f"{self.label} updated."), "success")
        return True

    def delete(self, form):
        item = self._find(form)
        if item is None:
            return False
        old_paths = [getattr(item, ff.attr, None) for ff in self.files]
        db.session.delete(item)
        db.session.commit()
        remove_unreferenced(old_paths)
        flash(self._msg("delete", f"{self.label} deleted."), "info")
        return True

    def toggle(self, form):
        item = self._find(form)
        if item is None:
            return False
        item.is_active = not item.is_active
        db.session.commit()
        flash(self._msg("toggle", "Status updated."), "success")
        return True

    # --------------------------------------------------------------- dispatch
    def dispatch(self, form, files, action_map=None, **extra):
        """Run the action named in the form. Never raises: problems become flash messages."""
        action = form.get("action", "")
        if action_map is not None:
            action = action_map.get(action, "")
        try:
            if action == "add" and "add" in self.allow:
                return self.add(form, files, **extra)
            if action in ("edit", "update") and "edit" in self.allow:
                return self.edit(form, files)
            if action == "delete" and "delete" in self.allow:
                return self.delete(form)
            if action == "toggle" and "toggle" in self.allow:
                return self.toggle(form)
        except (SQLAlchemyError, OSError, ValueError, TypeError) as exc:
            db.session.rollback()
            current_app.logger.exception("Admin action failed: %s", exc)
            flash("Something went wrong while saving. Nothing was changed - please try again.", "danger")
        return False

    def list(self, **filters):
        q = self.model.query
        if filters:
            q = q.filter_by(**filters)
        if self.order_by:
            return q.order_by(*self.order_by(self.model)).all()
        if hasattr(self.model, "created_at"):
            return q.order_by(self.model.order, self.model.created_at.desc()).all()
        return q.order_by(self.model.order).all()
