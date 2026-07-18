# Anti-Patterns to Avoid

This document catalogs anti-patterns discovered during code reviews. **Mandatory reading during planning and before committing.**

---

## 1. Fragile Relative Import Paths

**Problem:** Using `sys.path.insert` with relative paths to import local packages.

```python
# BAD - breaks if repo layout changes or package installed
lang_practice_root = Path(__file__).resolve().parent.parent / "language-practice"
sys.path.insert(0, str(lang_practice_root / "src"))
import language_practice
```

**Fix:** Add as proper dependency (editable install in `pyproject.toml` / `requirements.txt`) or use `importlib.resources`.

---

## 2. Missing Input Validation on Numeric Entry Fields

**Problem:** `Entry` widgets bound to `IntVar`/`DoubleVar` accept any text; `int()`/`float()` crashes in worker thread.

```python
# BAD - crashes in background thread if user types "abc"
ttk.Entry(textvariable=self.count_var)  # IntVar
# ...later in worker...
count = self.count_var.get()  # raises ValueError
```

**Fix:** Add `validatecommand` to restrict input, or wrap conversion in `try/except` with user-friendly error.

---

## 3. Silent Config Corruption Masking

**Problem:** Corrupted `settings.json` silently returns defaults instead of warning user.

```python
# BAD - masks corruption
try:
    return json.loads(path.read_text())
except Exception:
    return DEFAULT_SETTINGS  # user never knows file was corrupt
```

**Fix:** Log warning, show toast/notification, backup corrupt file before overwriting.

---

## 4. Temp File Cleanup Race Conditions

**Problem:** Fixed-delay cleanup may delete file while still playing.

```python
# BAD - 1 second may be too short
self.window.after(1000, lambda: path.unlink(missing_ok=True))
```

**Fix:** Track temp files in a list; clean up on wizard close / app exit via `atexit` or explicit cleanup method.

---

## 5. Broad Exception Handling in Workers

**Problem:** `except Exception` hides real errors and makes debugging harder.

```python
# BAD
try:
    do_work()
except Exception as exc:
    self.window.after(0, lambda e=exc: self._on_error(e))
```

**Fix:** Catch specific exceptions; let unexpected ones propagate to crash reporter / log with traceback.

---

## 6. Redundant Computation in Hot Paths

**Problem:** Recomputing same derived data on every trace callback.

```python
# BAD - called on every engine/language change
def _sync_voice_settings(self):
    supported = engines_supporting_language(lang_code, self.app.piper_voice_options)
    ...
```

**Fix:** Cache results per language with `@lru_cache` or instance dict.

---

## 7. Misleading UI Labels

**Problem:** Button says "Save as Preset" but saves all settings as defaults.

```python
# BAD - no way to create named custom presets
ttk.Button(text="Save as Preset", command=self._save_preset)

def _save_preset(self):
    self.settings.update(self._collect_settings())  # overwrites defaults
    save_app_settings(self.app.settings)
```

**Fix:** Match label to behavior ("Save as Defaults") or implement named preset storage.

---

## 8. Inconsistent Context Menu Application

**Problem:** Some `Entry` widgets get right-click menus, others don't.

```python
# BAD - inconsistent UX
add_context_menu(self.seed_entry)      # has menu
add_context_menu(self.count_entry)     # missing!
```

**Fix:** Apply `add_context_menu()` to ALL `Entry`/`Text` widgets uniformly (helper or factory function).

---

## 9. Case/Accent-Sensitive String Matching for User Input

**Problem:** User enters "avo" but vocab has "avô" → no match.

```python
# BAD
base_word_obj = next((w for w in words if w.pt.lower() == base_word), None)
```

**Fix:** Normalize both sides (NFD + strip combining marks + lower).

---

## 10. Missing Dependency Health Checks at Startup

**Problem:** Optional heavy dependency (`language-practice`) fails silently until user clicks "Generate".

```python
# BAD - import inside worker thread
def _generate_pairs(self):
    import language_practice  # fails here, confusing error
```

**Fix:** Check at wizard `__init__`; show friendly dialog if missing with install instructions.

---

## Checklist for PRs

Before committing, verify:

- [ ] No `sys.path.insert` hacks for local packages
- [ ] All numeric `Entry` widgets have validation
- [ ] Config corruption logs warning + backs up file
- [ ] Temp files tracked and cleaned on exit
- [ ] Worker threads catch specific exceptions
- [ ] Hot-path computations cached
- [ ] UI labels match actual behavior
- [ ] All `Entry`/`Text` widgets have context menus
- [ ] User-input string matching is normalized
- [ ] Optional dependencies checked at feature entry point