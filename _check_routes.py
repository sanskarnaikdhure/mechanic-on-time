import app
print("Routes loaded:")
for r in sorted(app.app.url_map.iter_rules(), key=lambda x: x.rule):
    methods = r.methods - {"HEAD", "OPTIONS"}
    print(f"  {r.rule}  {methods}")
