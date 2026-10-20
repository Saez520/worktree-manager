# Gestor de worktrees

Gestor standalone para crear, completar, limpiar y recuperar worktrees de un
repositorio Git. El proyecto no conoce FlowTask ni depende de sus rutas, refs
heredadas o mecanismos de coordinación.

## Arquitectura

`worktree.sh` es el entrypoint y delega el lifecycle en el paquete Python
`worktree_manager`, que se ejecuta con `python3 -m worktree_manager`. El paquete
es la única implementación del lifecycle: no existe un motor shell alternativo.

El paquete se organiza en módulos con una responsabilidad cada uno:

| Módulo | Responsabilidad |
| --- | --- |
| `worktree_manager.cli` | Interfaz de línea de comandos y contrato de salida. |
| `worktree_manager.configuration` | Lectura y validación de la configuración `key=value`. |
| `worktree_manager.worktree_lifecycle` | Operaciones `create`, `complete`, `cleanup` y `prune`. |
| `worktree_manager.target_direct_adapter` | Operaciones `target-direct` sobre un submodule. |
| `worktree_manager.recovery_manager` | Recuperación de transacciones pendientes. |
| `worktree_manager.transaction_journal` | Journal durable de transacciones. |
| `worktree_manager.backup_store` | Respaldos y refs de respaldo. |
| `worktree_manager.lock_manager` | Exclusión mutua entre procesos. |
| `worktree_manager.git_repository` | Acceso a Git desde un único punto. |
| `worktree_manager.mcp_server` | Servicio MCP por stdio. |

La configuración se valida como datos `key=value`, nunca como código shell.

El instalador o consumidor que integre este repositorio debe materializarlo
como una única fuente de implementación.

## Configuración y lifecycle

La configuración permite seleccionar `worktrees_dir`, `state_dir`,
`backup_dir`, `backup_ref_prefix`, `branch_prefix` y `lock_dir`. Parent-only
admite `create`, `complete`, `cleanup`, `recover`, `prune` y `list`, con locks,
journals, recuperación y preservación explícita.

`complete` conserva recursos ante conflictos o drift. `cleanup` no integra;
retirar cambios no integrados exige `--discard`. La preservación requiere
opt-in y los conflictos de restauración quedan para intervención humana.

## Target-direct

Target-direct opera sobre el repositorio submodule indicado: no crea un
worktree del parent ni modifica su `HEAD`. Requiere identidad explícita de
target/parent, ruta del submodule y `--link-parent staged-only`. `create`
prepara el worktree del target; `link-parent` registra únicamente el gitlink;
`abort`, `complete` y `recover` conservan snapshot y journal y se detienen ante
drift ambiguo. Requiere exactamente Git 2.54.0.

## Uso

```text
worktree.sh [--repo ABS] [--config ABS] create <id> [--base BRANCH]
worktree.sh [globales] complete <id> [--preserve-dirty]
worktree.sh [globales] cleanup <id> [--discard]
worktree.sh [globales] recover [<transaction-id>]
worktree.sh [globales] prune | list
```

La interfaz target-direct y el contrato de salida JSON están documentados en
[`docs/cli-contract-v1.md`](docs/cli-contract-v1.md). Las pruebas ejecutables
se encuentran en `tests/`.

## Distribución

Este repositorio es la fuente de verdad del gestor. FlowTask lo integra como
submodule y añade únicamente un adaptador de compatibilidad; la documentación
de esa integración vive en el repositorio consumidor.
