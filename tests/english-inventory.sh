#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ALLOWLIST="$ROOT/tests/english-allowlist.txt"

[[ -f "$ALLOWLIST" ]] || { printf '%s\n' "Missing English allowlist: $ALLOWLIST" >&2; exit 1; }

awk -F'|' '
  /^#/ { next }
  NF != 5 { printf "%s:%d: allowlist record must have category|literal|scope|reason|owner\n", FILENAME, NR; bad=1; next }
  $1 !~ /^(command-or-option|path-or-env|schema-or-code|identifier-or-object|external-or-protocol|fixture-data)$/ { printf "%s:%d: invalid allowlist category: %s\n", FILENAME, NR, $1; bad=1 }
  $2 == "" || $3 == "" || $4 == "" || $5 == "" { printf "%s:%d: allowlist fields may not be empty\n", FILENAME, NR; bad=1 }
  END { exit bad }
' "$ALLOWLIST"

# These markers are deliberately limited to controlled Spanish prose patterns.
# Machine literals are classified in the allowlist and are never used as a
# whole-line or whole-message exemption.
pattern='[áéíóúñÁÉÍÓÚÑ¿¡]|(^|[^[:alpha:]])(Se requiere|No se |No pude |La configuración|El repositorio|La rama|La ruta|Opción|Falta |Aviso:|Advertencia:|Conflicto |intervención|inválid|desconocid|preservación|transacción|cierre|Ejecutá|reintentá|corregí|limpiá|usá|archivo|directorio|repositorio|configuración)([^[:alpha:]]|$)'
status=0
while IFS= read -r file; do
  [[ "$file" == "$ROOT/tests/english-inventory.sh" ]] && continue
  if matches="$(grep -nE "$pattern" "$file" || true)"; then
    if [[ -n "$matches" ]]; then
      printf '%s\n' "$matches" | sed "s#^#$file:#" >&2
      status=1
    fi
  fi
done < <(find "$ROOT" -type f -name '*.sh' -print | sort)

printf '%s\n' 'MCP: absent/not verified; no Worktree Manager MCP implementation or contract is inventoried.'
if (( status != 0 )); then
  printf '%s\n' 'English inventory failed: unclassified human text found.' >&2
  exit "$status"
fi
printf '%s\n' 'English inventory passed: all in-scope shell text is English or literal-level classified.'
