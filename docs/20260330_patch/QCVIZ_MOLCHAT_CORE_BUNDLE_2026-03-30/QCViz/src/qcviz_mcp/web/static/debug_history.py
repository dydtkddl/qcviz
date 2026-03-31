import re

with open("version02/src/qcviz_mcp/web/static/app.js", "r", encoding="utf-8") as f:
    text = f.read()

# Let's check how App.upsertJob works.
# Is it persisting anything locally?
m = re.search(r"upsertJob: function.*?\},", text, re.DOTALL)
if m:
    print(m.group(0))

