Vas a implementar un cambio, ejecutar una spec o iniciar un flujo. ¿Quieres crear un worktree para hacerlo aislado?

Esta guía explica cómo usar el gestor `worktree-for-agents` para trabajar
aislado en un worktree antes de tocar la rama principal.

## Las siete herramientas

El servicio MCP expone exactamente siete herramientas:

- `worktree_create`: crea un worktree y su rama para un identificador de trabajo.
- `worktree_complete`: integra el worktree en la rama base y retira el worktree.
- `worktree_cleanup`: retira el worktree y su rama sin integrar.
- `worktree_recover`: recupera una transacción pendiente por su identificador.
- `worktree_list`: lista los worktrees del repositorio.
- `worktree_prune`: poda la información de worktrees que ya no existen.
- `worktree_status`: muestra el estado de un trabajo.

Todas exigen una ruta absoluta de repositorio Git en `repo`.

## Cuándo ofrecer el worktree

Antes de trabajar en la rama principal, ofrece crear un worktree con
`worktree_create`. Trabaja dentro del worktree y luego integra con
`worktree_complete`. Si el trabajo se descarta, usa `worktree_cleanup`.

## Lanzamiento sin bin

El paquete no expone bin ni `npx`. El servicio MCP se lanza con Node y la
ruta absoluta del paquete:

```sh
node <paquete>/mcp-server.mjs
```

La CLI se lanza del mismo modo:

```sh
node <paquete>/worktree.mjs --version
```

El diagnóstico de la instalación se obtiene con:

```sh
node <paquete>/setup.mjs
```
