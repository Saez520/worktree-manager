# Instalación y uso del gestor de worktrees

Esta guía explica cómo instalar el gestor desde un clon aislado y cómo usarlo
sobre un repositorio de prueba. No cubre la integración con ningún consumidor:
esa parte se documenta en el repositorio que integra el gestor.

Los ejemplos usan `$HOME` porque `--repo` exige una ruta absoluta. Sustitúyelo
por la ruta real donde clones el gestor.

## 1. Requisitos

Comprueba las versiones disponibles:

```sh
python3 --version
git --version
```

- **Python 3.9 o posterior.** El entrypoint `worktree.sh` sólo comprueba que
  `python3` esté en el `PATH`; no verifica la versión. El piso de 3.9 lo
  valida el instalador del consumidor, no este repositorio.
- **Git 2.17.0 o posterior**, por `git worktree remove`. La línea base de las
  pruebas es Git 2.54.0. El gestor no comprueba la versión de Git en tiempo de
  ejecución.
- **`bash`** para ejecutar las suites de pruebas.

## 2. Clonar e instalar

```sh
git clone git@github.com:Saez520/worktree-manager.git "$HOME/worktree-manager"
cd "$HOME/worktree-manager"
./worktree.sh --version
```

La salida es `1.0.0`. No hay `pip install`, ni paquete que instalar, ni
dependencias que resolver: el gestor usa sólo la biblioteca estándar de Python.

## 3. Un repositorio de prueba

El gestor exige que la ruta del worktree esté ignorada por Git, y
`.worktrees/` en el `.gitignore` cumple esa condición.

```sh
mkdir "$HOME/demo" && cd "$HOME/demo"
git init -b main
git config user.name "Demo"
git config user.email "demo@example.invalid"
printf 'base\n' > file
printf '.worktrees/\n' > .gitignore
git add file .gitignore
git commit -m "base"
```

Crea el worktree:

```sh
"$HOME/worktree-manager/worktree.sh" --repo "$HOME/demo" create demo --base main
```

Qué deja cada paso:

- `git init` crea el repositorio y su rama `main`.
- El commit inicial fija la base sobre la que se construye el worktree.
- `create` crea la rama `worktree/demo`, el worktree en `$HOME/demo/.worktrees/demo`
  y el journal de la transacción en el directorio de estado del repositorio.

Comprueba el estado:

```sh
"$HOME/worktree-manager/worktree.sh" --repo "$HOME/demo" list
```

Trabaja dentro del worktree y luego intégralo:

```sh
cd "$HOME/demo/.worktrees/demo"
printf 'cambio\n' >> file
git add file
git commit -m "cambio"
cd "$HOME/demo"
"$HOME/worktree-manager/worktree.sh" --repo "$HOME/demo" complete demo --base main
```

`complete` exige que el repositorio esté en la rama base, que el worktree no
tenga cambios sin commitear y que el destino tampoco los tenga, salvo que se
use `--preserve-dirty`. Al terminar, el cambio queda integrado como un commit
de squash en `main`, y el worktree y su rama se retiran.

Para dejar un commit de cierre diciente, pasa `--title` y, opcionalmente,
`--body`:

```sh
"$HOME/worktree-manager/worktree.sh" --repo "$HOME/demo" complete demo --base main \
  --title "Cierre de demo" --body "Entrega: cambio integrado. Motivo: verificacion."
```

Si no se pasa `--title`, el gestor usa el fallback generico:
`Complete <work_id> (generic closure)` con el cuerpo
`No delivery description was available at closure time.`.

## 4. Configuración

La configuración es un archivo de `clave=valor`. El gestor lo toma de
`.worktree-manager.conf` en la raíz del repositorio, o del archivo que se le
pase con `--config`, que debe existir y ser una ruta absoluta. Si se pasan
ambos, `--config` prevalece. Después, la variable de entorno
`WORKTREE_MANAGER_<CLAVE>`, con la clave en mayúsculas, reemplaza el valor
leído del archivo.

Las once claves y sus valores por defecto son:

| Clave | Por defecto | Restricción |
|---|---|---|
| `worktrees_dir` | `.worktrees` | No puede empezar por `-` |
| `branch_prefix` | `worktree/` | — |
| `state_dir` | `worktree-manager` | Ruta relativa segura |
| `backup_dir` | `backups` | No es una ruta absoluta y no contiene `..` |
| `backup_ref_prefix` | `worktree-manager/backups` | Sin `..` |
| `lock_dir` | `locks` | Ruta relativa segura |
| `prepare_command` | `''` (vacío) | Requerida cuando `prepare_enabled=true` |
| `verify_command` | `''` (vacío) | Requerida cuando `verify_enabled=true` |
| `prepare_enabled` | `false` | `true` o `false` |
| `verify_enabled` | `false` | `true` o `false` |
| `preserve_dirty` | `false` | `true` o `false` |

Cada clave puede aparecer una sola vez. Una clave desconocida, una línea sin
`=`, un booleano inválido o una ruta insegura se rechazan como
`invalid_configuration` con código de salida `3`, antes de cualquier efecto.

## 5. Contratos de salida

- `--json` publica un único documento JSON con siete claves: `contract_version`,
  `tool_version`, `operation`, `result`, `data`, `warnings` y `error`.
- `--request-json <archivo|->` publica el mismo documento de nueve claves que
  usa el transporte MCP: las siete anteriores más `repository` y
  `transaction_id`. Acepta `--json` de forma opcional y el documento publicado
  no cambia.
- Un dry run de `create` publica `planned: true` y no crea worktree ni rama.
  `init_submodules_result` es `planned` o `not_requested`, y `prepare` y
  `verify` son `planned` o `skipped`.
- El servicio MCP se publica por stdio y expone siete herramientas:

```sh
PYTHONPATH=. python3 -m worktree_manager.mcp_transport
```

## 6. Pruebas

```sh
bash tests/cli-usage.sh
bash tests/cli-json.sh
bash tests/compatibility.sh
bash tests/smoke.sh
bash tests/parity.sh
PYTHONPATH=. python3 -m unittest discover -s tests -p 'test_*.py'
PYTHONPATH=. python3 -m unittest discover -s tests -p 'test_mcp*.py' -v
```

## 7. Consumo como submódulo

Un repositorio consumidor puede materializar el gestor como submódulo. La
regla es única: el checkout materializado y el gitlink registrado deben ser el
mismo commit. El gestor no se empaqueta ni se copia a un target instalado, y no
se promete una distribución portable.

## 8. Solución de problemas

- **`python3` no está en el `PATH`.** El entrypoint termina con el código `127`
  y el mensaje
  `worktree manager requires Python 3 (python3) on PATH; install Python 3 and retry.`
- **Falta el punto de entrada del paquete.** El entrypoint termina con el
  código `126` y el mensaje
  `worktree manager Python entry point is missing: <ruta>/worktree_manager/__main__.py`.
- **La ruta del repositorio es relativa.** La operación se rechaza con el
  código `invalid_repository`, el código de salida `3` y el mensaje
  `Repository path must be absolute`.
- **La versión de Python es anterior a 3.9.** El instalador del consumidor lo
  informa como `python <version> is older than the required 3.9`. El entrypoint
  de este repositorio no comprueba la versión.

## 9. Qué no cubre

Esta guía no cubre la integración con un consumidor: ni el adaptador, ni el
bridge, ni la validación del gitlink, ni el procedimiento de instalación del
consumidor. Eso se documenta en el repositorio consumidor.
