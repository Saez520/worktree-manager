# Gestor de worktrees

Gestor Bash standalone para crear, completar, limpiar y recuperar worktrees de
un repositorio Git.

## Arquitectura

`worktree.sh` es el entrypoint y delega el lifecycle parent-only a
`lib/worktree-manager-core.sh`; el core carga
`lib/worktree-manager-target-direct.sh` para operar directamente sobre un
submodule. La configuración se valida como datos `key=value`, nunca como
código shell.

El gestor mantiene una única implementación del core y del módulo target-direct;
no se deben mantener copias alternativas de ninguno de ellos.

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

Este repositorio contiene la implementación completa del gestor y su
documentación, incluidos el contrato de la CLI y las pruebas ejecutables.
