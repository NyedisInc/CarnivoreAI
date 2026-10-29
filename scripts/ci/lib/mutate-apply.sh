
mutate_apply() {
  "${PY:-python3}" - "$1" "$2" <<'PYEOF'
import sys
path, expr = sys.argv[1], sys.argv[2]
text = open(path, encoding='utf-8').read()
old, new = expr.split('||=>||')
count = text.count(old)
if count == 0:
    sys.exit('mutation target not found: ' + old[:70])
if count > 1:
    sys.exit('mutation target ambiguous (%d occurrences): %s' % (count, old[:70]))
open(path, 'w', encoding='utf-8').write(text.replace(old, new, 1))
PYEOF
}
