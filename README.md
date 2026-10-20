# Gestor de worktrees

Gestor standalone para crear, completar, limpiar y recuperar worktrees de un
repositorio Git. El proyecto no conoce FlowTask ni depende de sus rutas, refs
heredadas o mecanismos de coordinación.

## Requisitos

- **Python 3.9 o posterior.** El entrypoint sólo comprueba que `python3` esté
  disponible en el `PATH`; no verifica la versión. El piso de 3.9 es el que
  valida el instalador del consumidor. El paquete usa sólo la biblioteca
  estándar.
- **Git 2.17.0 o posterior**, por `git worktree remove`, que es el comando más
  reciente que usa el gestor. La línea base de las pruebas es Git 2.54.0. El
  gestor no comprueba la versión de Git en tiempo de ejecución.
- **`bash`** para ejecutar las suites de pruebas.

## Instalación

El gestor se instala clonando el repositorio. No hay paquete que instalar ni
dependencias que resolver.

```sh
git clone git@github.com:Saez520/worktree-manager.git worktree-manager
cd worktree-manager
./worktree.sh --version
```

La última orden imprime `1.0.0`.

## Uso rápido

Las opciones globales van antes del subcomando y `--repo` exige una ruta
absoluta.

```text
worktree.sh [--repo ABS] [--config ABS] [--json] create <id> [--base BRANCH] [--init-submodules] [--prepare] [--verify]
worktree.sh [globales] complete <id> [--preserve-dirty]
worktree.sh [globales] cleanup <id> [--discard]
worktree.sh [globales] recover [<transaction-id>]
worktree.sh [globales] prune
worktree.sh [globales] list
```

Target-direct opera sobre el repositorio indicado en `--repo` y no crea un
worktree del parent ni modifica su `HEAD`. Su sintaxis coloca `--parent-repo`
después de la acción y exige `--submodule-path` en `create`:

```text
worktree.sh [--repo ABS] target-direct <acción> <id> --parent-repo <parent> [--target submodule] [--submodule-path <REL>] [--base BRANCH] [--link-parent staged-only] [--descriptor PATH]
```

Las acciones son `create`, `link-parent`, `abort`, `complete` y `recover`, y el
único modo de enlace admitido es `--link-parent staged-only`.

`--json` publica un único documento JSON. `--request-json <archivo|->` publica
el mismo sobre de nueve claves que usa el transporte MCP, y acepta `--json` de
forma opcional. Un dry run de `create` publica `planned: true` y no crea
worktree ni rama.

El servicio MCP se publica por stdio:

```sh
PYTHONPATH=. python3 -m worktree_manager.mcp_transport
```

## Configuración

La configuración es un archivo opcional de `clave=valor`, seleccionado con
`--config` o tomado de `.worktree-manager.conf` en la raíz del repositorio.
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

Cada clave puede aparecer una sola vez. Las claves desconocidas, las líneas mal
formadas, los booleanos inválidos y las rutas inseguras se rechazan como
`invalid_configuration` con código de salida `3`. La variable de entorno
`WORKTREE_MANAGER_<CLAVE>`, con la clave en mayúsculas, reemplaza el valor
leído del archivo.

## Arquitectura

`worktree.sh` es el entrypoint y delega el lifecycle en el paquete Python
`worktree_manager`, que se ejecuta con `python3 -m worktree_manager`. El paquete
es la única implementación del lifecycle: no existe un motor shell alternativo.

El paquete se organiza en módulos con una responsabilidad cada uno:

| Módulo | Responsabilidad |
| --- | --- |
| `worktree_manager.cli` | Despachador de comandos, despacho target-direct y contrato de salida. |
| `worktree_manager.configuration` | Lectura y validación de la configuración `clave=valor`. |
| `worktree_manager.models` | Valores de dominio compartidos: resultados, errores e identidades. |
| `worktree_manager.output` | Publicación del resultado como texto legible o como JSON. |
| `worktree_manager.git_repository` | Acceso compartido a Git para los módulos del lifecycle. |
| `worktree_manager.worktree_lifecycle` | Operaciones `create`, `complete`, `cleanup` y `prune`. |
| `worktree_manager.target_direct_adapter` | Operaciones target-direct sobre un submódulo. |
| `worktree_manager.recovery_manager` | Recuperación de transacciones pendientes. |
| `worktree_manager.transaction_journal` | Journal durable de transacciones y enlaces. |
| `worktree_manager.backup_store` | Referencias de respaldo retenidas. |
| `worktree_manager.lock_manager` | Exclusión mutua entre procesos. |
| `worktree_manager.state_digest` | Digest canónico del estado del repositorio y de un plan. |
| `worktree_manager.mcp_server` | Servicio MCP publicado por stdio. |
| `worktree_manager.mcp_contract` | Contratos estrictos y versionados de petición y de sobre. |
| `worktree_manager.mcp_operations` | Fachada sobre los servicios de lifecycle y de recuperación. |
| `worktree_manager.mcp_transport` | Punto de entrada del transporte por stdio. |

El paquete contiene además el marcador de paquete `__init__.py` y el punto de
entrada `__main__.py`, que es lo que ejecuta `python3 -m worktree_manager`.

## Pruebas

```sh
bash tests/cli-usage.sh
bash tests/cli-json.sh
bash tests/compatibility.sh
bash tests/smoke.sh
bash tests/parity.sh
PYTHONPATH=. python3 -m unittest discover -s tests -p 'test_*.py'
PYTHONPATH=. python3 -m unittest discover -s tests -p 'test_mcp*.py' -v
```

## Documentación

- [Contrato de salida de la CLI](docs/cli-contract-v1.md) — contrato.
- [Contrato del servicio MCP](docs/mcp-contract.md) — contrato.
- [Guía de instalación y uso](docs/installation.md) — guía.
- [Histórico bash → Python](docs/history-bash-to-python.md) — memoria, no contrato.

Los contratos fijan el comportamiento verificable. La guía explica cómo usarlo.
El histórico registra la transición y no sustituye a los contratos.

## Fuente y distribución

Este repositorio es la fuente de verdad de la implementación, de los contratos,
de la instalación y del histórico del gestor.

El consumidor que integra este repositorio documenta el adaptador, el bridge y
la frontera del submódulo: **la documentación de esa integración vive en el
repositorio consumidor**. El gestor no mantiene una copia vendorizada de sí
mismo y no conoce al consumidor.
