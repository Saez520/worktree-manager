# Histórico: del backend shell al backend Python

Este documento es memoria del proyecto, no un contrato. No repite los contratos
vigentes y no contiene instrucciones de shell. El comportamiento verificable
está en [cli-contract-v1.md](cli-contract-v1.md) y en
[mcp-contract.md](mcp-contract.md).

## Qué había

El gestor implementaba su lifecycle en shell. Ese backend vivía en `worktree.sh`
y en dos módulos del directorio `lib/`:
`lib/worktree-manager-core.sh` para el ciclo parent-only y
`lib/worktree-manager-target-direct.sh` para la ruta target-direct. El mismo
repositorio mantenía en paralelo la implementación Python, y el harness
`tests/parity.sh` comparaba ambos backends entre sí: arrancaba un repositorio
de prueba independiente para cada implementación y exigía que publicaran el
mismo estado de salida, la misma salida JSON y el mismo estado de repositorio.

## Qué hay

`worktree.sh` valida que `python3` esté disponible y que el punto de entrada
`worktree_manager/__main__.py` exista, y a continuación ejecuta
`python3 -m worktree_manager`. El paquete `worktree_manager` es la única
implementación del lifecycle: no hay un motor shell alternativo. Está formado por
16 módulos, más el marcador de paquete `__init__.py` y el punto de entrada
`__main__.py`. El servicio MCP se publica por stdio.

## Por qué

Una sola implementación evita dos comportamientos divergentes para la misma
operación. El harness comparaba la equivalencia entre los dos backends, no la
corrección de cada uno: demostraba que un camino replicaba al otro, no que
ninguno de los dos estuviera mal. El paquete usa únicamente la biblioteca
estándar de Python, sin dependencias externas.

## Estado real de `tests/parity.sh`

`tests/parity.sh` tiene 25 líneas. No compara backends: ejecuta `list --json`
desde dos directorios de trabajo distintos y exige que ambos documentos JSON
sean idénticos, y comprueba que la invocación sin el CLI canónico disponible se
rechaza. Su nombre conserva la referencia a la paridad; su contenido verifica la
resolución del directorio de trabajo.

## Dónde vive la evidencia

La evidencia de las fases retiradas permanece en los tags `phase-3-4`
(`8c7a569`) y `phase-5` (`671effb`). El commit que purga la evidencia del árbol
activo la deja trazada en su propio mensaje. Los tags no se re-publican y el
historial no se reescribe; el contenido anterior se consulta con `git show`.

## Qué no es

Este documento no es un contrato, no duplica los contratos y no da
instrucciones de shell. Para el comportamiento vigente, ver
[cli-contract-v1.md](cli-contract-v1.md) y [mcp-contract.md](mcp-contract.md).
