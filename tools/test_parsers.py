import importlib.util, re, sys
spec = importlib.util.spec_from_file_location("mg", "scripts/memory_guard.py")
mg = importlib.util.module_from_spec(spec); spec.loader.exec_module(mg)
spec = importlib.util.spec_from_file_location("ba", "scripts/build_atlas.py")
ba = importlib.util.module_from_spec(spec); spec.loader.exec_module(ba)

note = """# Example ADR

Here is what a feature note looks like:

```
## Observations
- [decision] PHANTOM claim from the example ^c7f2a1

## Relations
- depends_on [[Billing]]
- part_of [[Core]]
```

~~~md
- depends_on [[TildeFence]]
~~~

Inline syntax like `- depends_on [[InlineExample]]` is explained in prose.

## Observations
- [fact] Deploys go through the `oidc-deploy` role only

## Relations
- depends_on [[Access Model]]
"""
REL = r"^\s*-\s+(?:\"[^\"]+\"|[A-Za-z_][A-Za-z0-9_]*)?\s*\[\[([^\]]+)\]\]"
ok = 0; bad = 0
def check(name, cond, detail=""):
    global ok, bad
    print(("  PASS " if cond else "  FAIL ") + name + ("  " + detail if detail else ""))
    ok += cond; bad += (not cond)

rels = [t for _, t in ba.relations_of(note)]
check("only the declared relation survives (atlas)", rels == ["Access Model"], str(rels))
guard_rels = re.findall(REL, mg.strip_code(note, inline=True), re.M)
check("only the declared relation survives (guard)", guard_rels == ["Access Model"], str(guard_rels))
total, cats = ba.observation_stats(note)
check("the fenced example claim is not counted", total == 1 and cats == {"fact": 1}, str(cats))
obs = ba.observation_list(note)
check("backticked words stay in the claim text", obs and "oidc-deploy" in obs[0]["text"], obs[0]["text"] if obs else "none")
check("line count preserved", len(mg.strip_code(note).split("\n")) == len(note.split("\n")))
# the gate must be able to fail: the old parse, on the raw text, finds the phantoms
old = re.findall(REL, note, re.M)
check("negative: the OLD parse finds phantom edges", set(old) >= {"Billing", "Core", "TildeFence"}, str(old))
print("\n%d passed, %d failed" % (ok, bad)); sys.exit(1 if bad else 0)
