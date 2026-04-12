# Módulo: Portal Docente — Vista Dashboard.

**Recurso UI (Mockup) ULTRA OBLIGATORIO:**   `ADAM-EDU\docs\planPlataforma\Mockups\profesor\Dashboard_Portal_Profesor.html`
Este es el archivo base para maquetar las vistas y componentes en React, del dashboard docente, debes si o si hacer este mismo diseño frontend, con la mejores practicas de UI/UX responsive y obviamente encajando el backend con esta vista. 
***

**Regla importante:**   
Debes usar Tanstack Query como se ha venido trabajando en el proyecto, para que toda informacion que se tenga que actualizar se actualice automaticamente sin que el usuario tenga que darle refresh manualmente. 
***

## 1. Accesos Directos (Quick Actions — Tarjetas Superiores)

Esta sección define el comportamiento de los tres botones de acción rápida ubicados en la parte superior del dashboard.

### 1.1 Crear Nuevo Caso

El sistema expone **dos puntos de acceso** para esta acción:

- **Tarjeta superior del dashboard** (Quick Action card).
- **Botón principal** en la tabla inferior de "Casos Activos".

**Comportamiento:** Ambos CTAs deben enrutar al docente a la vista de creación de casos, donde esta el formulario que llena el docente para crear un nuevo caso.

```
Destino de navegación: Diseñador de Casos ADAM o sea el formulario que esta en la siguiente ruta: ADAM-EDU\frontend\src\features\teacher-authoring\AuthoringForm.tsx (No debes tocar nada de esta vista, solo enrutar los CTAs aquí)
```

> Ambos puntos de acceso deben ser idénticos en comportamiento. No se debe implementar lógica diferenciada entre ellos.

***

### 1.2 Gestión de Casos

**Comportamiento:** Este botón ejecuta un **scroll suave (anchor)** dentro de la misma vista, desplazando la ventana hacia la sección de la tabla inferior "Casos Activos".

- No redirige a ninguna ruta externa.
- Se debe usar `scroll-behavior: smooth` o el equivalente en React (e.g., `element.scrollIntoView({ behavior: 'smooth' })`).

***

### 1.3 Reportes Globales *(Alcance V1)*

**Comportamiento (Versión 1 — Sin redirección):**

Al hacer clic, el frontend debe:

1. **Capturar el evento** de clic sin alterar la ruta de navegación actual.
2. **Mostrar un feedback visual** mediante uno de los siguientes mecanismos:
   - Toast notification con el mensaje **"Próximamente"** o **"Generando reporte..."**.
   - Alerta visual nativa del sistema de diseño seleccionado.

> Esta funcionalidad queda pendiente para una versión futura. La UI debe comunicar esto de forma clara y no-bloqueante.

***

## 2. Sección: Cursos Activos

### 2.1 Lógica de Renderizado (Backend)

El backend debe proveer el listado y la información de los cursos **asignados al docente autenticado** en la sesión activa. El endpoint correspondiente debe filtrar los cursos por el `docente_id` del token de autenticación o averigua cual seria lo mejor segun cómo se estan haciendo las cosas en el proyecto.

### 2.2 Interacción y Routing (Frontend)

Como todavia no esta la vista o pantalla de un curso, al hacer clic en la tarjeta de un curso específico (botón **"Entrar al curso"**), debes dejar listo el backend o la ruta bien hecha para que en una proxima fase sea facil conectar esa pantalla de un curso con ese boton. 

> El método elegido debe permitir que la vista de destino cargue el contexto correcto del curso sin requerir una nueva autenticación o selección manual.

***

## 3. Sección: Casos Activos (Tabla Consolidada)

### 3.1 Lógica de Negocio (Backend)

Esta tabla presenta una **vista consolidada global**, no limitada a un solo curso. Las reglas de filtrado son:

- Incluir únicamente los casos pertenecientes a **todos los grupos del docente autenticado**.
- Filtrar exclusivamente los casos cuya **fecha límite de entrega (`deadline`) no haya vencido** (i.e., `deadline >= fecha_actual`).

```sql
-- Lógica de filtrado conceptual
SELECT * FROM casos
WHERE docente_id = :docente_id
  AND deadline >= NOW()
ORDER BY deadline ASC;
```

### 3.2 Acciones por Caso (Fila de la Tabla)

Cada fila de la tabla expone **tres botones de acción** para el caso listado. A continuación se define el comportamiento esperado para la **Versión 1**, dado que no existen mockups detallados para estas sub-vistas.

***

#### 3.2.1 Acción: "Ver Caso"

**Comportamiento:**

Todavia es un boton que no enruta a otra vista, pero debes dejar todo listo para que en una proxima fase sea facil encajarlo.

***

#### 3.2.2 Acción: "Entregas"

**Comportamiento:**

Todavia es un boton que no enruta a otra vista, pero debes dejar todo listo para que en una proxima fase sea facil encajarlo.

Pero en un futuro seria algo como esto: 
"Redirige al docente a la **tabla de calificaciones de los estudiantes** para ese caso específico."

#### 3.2.3 Acción: "Editar" *(Limitación V1)*

> ⚠️ **Restricción de Versión 1:** En esta versión **no se permite la edición del cuerpo del texto del caso**.


Todavia es un boton que no enruta a otra vista o saca un modal debido a que la vista del caso todavia no esta hecha, pero debes dejar todo listo para que en una proxima fase sea facil encajarlo.

En un futuro seria algo como esto: 
**Comportamiento al hacer clic en "Editar":**

El frontend despliega un **Modal estándar** de la librería UI seleccionada del proyecto. Este modal expone **únicamente dos acciones permitidas** sobre la base de datos:

***

**Acción A — Actualizar Fecha/Hora Límite de Entrega**

| Campo | Descripción |
|---|---|
| Campo de DB | `deadline` (fecha y hora límite de entrega) |
| Tipo de input | `datetime-local` o componente DateTimePicker de la librería UI |
| Validación | La nueva fecha debe ser mayor a la fecha y hora actuales |
| Acción | `PATCH /casos/:caso_id` con el campo `deadline` actualizado |

***

**Acción B — Borrar / Archivar Caso**

| Campo | Descripción |
|---|---|
| Efecto | Elimina el caso de la vista de los estudiantes |
| Flujo | Requiere **confirmación previa** antes de ejecutar la operación |
| Confirmación | Modal secundario de confirmación o diálogo `Dialog` de la librería UI con mensaje explícito del riesgo |
| Acción | `DELETE /casos/:caso_id` o `PATCH /casos/:caso_id` con campo `archivado: true` (según estrategia de soft/hard delete definida en el backend) |

> ℹ️ Se recomienda implementar **soft delete** (campo `archivado` o `activo`) para preservar la integridad referencial con entregas y calificaciones ya registradas.

***