## Usuarios:

-   **Usuario docente.**

-   **Usuario estudiante.**

-   **Usuario administrador de la universidad.**

Actúa como un Arquitecto de Software Principal y Tech Lead. Tu tarea es diseñar la arquitectura y el plan de implementación para nuestro nuevo sistema educativo (ADAM EDU). El diseño debe ser altamente escalable, seguro (arquitectura multi-tenant para múltiples universidades) y mantener una deuda técnica estrictamente documentada y controlada. El cliente inicial tiene 600 usuarios, pero el diseño debe soportar crecimiento masivo.

- Fase 0: Preparación de Infraestructura y Entorno (Ultrathink)
Antes de implementar la fase de registro, evalúa críticamente y define la arquitectura base. Usaremos LangGraph integrado con Google Cloud Run para la orquestación escalable de agentes, y Supabase (PostgreSQL) para Auth y base de datos. Sé crítico: analiza si esta combinación es la óptima, cómo manejar el multi-tenancy (ej. Row Level Security en Supabase) y qué otros servicios faltan para tener un stack robusto.
1. Detalla los pasos arquitectónicos para configurar Supabase y Cloud Run correctamente para este caso de uso.
2. Define qué servidores MCP (Model Context Protocol) o Skills necesitamos dejar configurados hoy para que herramientas como Claude Code puedan operar autónomamente en este stack.

- Fase 1: Registro e Inicio de Sesión de Usuarios
Revisa los requerimientos de la Fase 1 proporcionados en el contexto/archivos adjuntos. No tomes los mockups como la verdad absoluta. Aplica un análisis crítico de UI/UX, flujo de usuario y seguridad. Propón refactorizaciones de arquitectura integrando nativamente Supabase Auth (ej. Custom Claims, SSO de Microsoft). Descarta elementos que no sigan los estándares modernos.

- Entregable: Especificación de Issues para GitHub
Como el plan es extenso, dividiremos el trabajo. Genera el contenido exacto para los Issues de GitHub correspondientes a la Fase 0 y la Fase 1. Cada Issue debe seguir estrictamente esta plantilla:

Título: Conciso y descriptivo.
Tipo: Feature / Bug / Enhancement / Task / Infra.
Descripción: Explicación clara de la necesidad técnica y de negocio.
Tareas (Checklist): Pasos de implementación atómicos, manejables y testeables.
Criterios de Aceptación: Condiciones de éxito detalladas, manejo de casos extremos y pruebas de validación necesarias.
Notas Técnicas: Archivos relacionados, consideraciones de integración (LangGraph, Supabase RLS, Cloud Run) y variables de entorno necesarias.

Preséntame este plan estructurado en un archivo de markdown en la ruta `/planPlataforma/fase0_y_fase1.md`. No modifiques código de la aplicación ni crees los Issues vía API hasta que yo apruebe este plan. 

## Módulo: Portal Docente - Activación e Inicio de Sesión

**Recurso UI (Mockup):** LOGIN_PROFESOR.html (Archivo base para maquetar las vistas y componentes en React). La ruta del mockup es esta: ADAM-EDU\docs\planPlataforma\Mockups\profesor\LOGIN_PROFESOR.HTML (Aqui debes pensar bien cómo encajar bien ese mockup con la arquitectura del frontend del sistema, y ademas en ese Mockup hay dos botones que dicen "Alternar a vista de Login", "Alternar a vista de Invitación", obviamente eso no se debe mostrar ahi debes ultra razonar como debe quedar esa pantalla profesionalmente.)

**1. Activación de Cuenta (Flujo de Invitación)**

-   **Restricción de acceso:** El sistema no cuenta con auto-registro público. La creación de un perfil docente depende exclusivamente del usuario Administrador al momento de asignarle un curso.

-   **Enlace único:** El docente recibe un enlace de invitación seguro. Al ingresar, el sistema lee el token de la URL y muestra la vista de "Activación", donde el campo del correo institucional ya debe estar prellenado y deshabilitado (disabled) por seguridad.

-   **Métodos de activación:** Para completar la activación y asegurar su cuenta, el docente tiene dos vías (arquitectura híbrida):

    -   **Vía SSO (Principal):** Hacer clic en "Vincular cuenta de Microsoft" para que la autenticación se delegue al proveedor oficial de la universidad (OAuth 2.0) de Microsoft.

    -   **Vía Credenciales (Respaldo):** Ingresar y confirmar una contraseña nueva que quedará asociada a su correo en la base de datos de ADAM.

**2. Inicio de Sesión (Login)**

-   **Autenticación Híbrida:** En sus visitas posteriores, el docente debe poder iniciar sesión eligiendo el método que prefiera: usando el botón de "Continuar con Microsoft" (SSO) o ingresando manualmente su correo institucional y contraseña.

-   **Redirección:** Tras una validación exitosa de las credenciales (o del token de Microsoft), el sistema debe redirigir automáticamente al docente a su panel principal (Dashboard_Portal_Profesor.html) cargando el contexto de los cursos y casos que tiene asignados (próxima feature).



## Portal Usuario Estudiante

## Módulo: Portal Estudiante - Activación e Inicio de Sesión

**Recurso UI (Mockup):** LOGIN_ESTUDIANTE.html (Archivo base para maquetar las vistas y componentes en React). La ruta del mockup es esta: ADAM-EDU\docs\planPlataforma\Mockups\estudiante\LOGIN_ESTUDIANTE.html (Aqui debes pensar bien cómo encajar bien ese mockup con la arquitectura del frontend del sistema, y ademas en ese Mockup hay dos botones que dicen "Probar vista de Login normal", "Probar vista de invitación", obviamente eso no se debe mostrar ahi debes ultra razonar como debe quedar esa pantalla profesionalmente.)

**Descripción General del Módulo:** Este módulo es la puerta de entrada para los estudiantes y opera bajo un modelo de "auto-enrolamiento". Dado que un estudiante puede pertenecer a múltiples cursos, la interfaz debe gestionar **dos flujos de navegación distintos** basándose en la presencia o ausencia de un token/código en la URL.

**1. Vista A: Activación y Matrícula (Acceso vía Link de Invitación)**

-   **Lógica de Renderizado (Frontend):** Si el estudiante ingresa mediante una ruta que contiene un token (ej. adam.edu/join/K9M2X1), el componente de React debe detectar este parámetro, consultar al backend la información del curso asociado a ese código y renderizar la vista de "Invitación" mostrando el contexto (Nombre de la asignatura y Docente).

-   **Captura de Identidad (Regla de Negocio Crítica):** Debido a que los docentes y administradores manejan múltiples grupos poblados, es **estrictamente necesario** registrar el *Nombre Completo* real del estudiante desde el primer momento para evitar perfiles anónimos.

-   **Métodos de Registro (Híbrido):**

    -   **Vía SSO Microsoft (Principal):** Al hacer clic en "Matricularme con Microsoft" (OAuth 2.0), el backend debe extraer automáticamente el nombre completo y el correo del proveedor de identidad, omitiendo la necesidad de llenar campos manuales.

    -   **Vía Credenciales (Respaldo):** El formulario debe solicitar: Nombre Completo, Email Institucional y Contraseña.

-   **Validación de Dominio Institucional:** El backend debe implementar una validación (*whitelist*) que rechaze cualquier intento de registro con correos genéricos (como @gmail.com o @hotmail.com), permitiendo únicamente el dominio oficial de la universidad.

-   **Resolución:** Una vez completado el registro, el backend vincula automáticamente el estudiante_id recién creado con el curso_id atado al token, y el frontend redirige al usuario a su Dashboard (Dashboard_Portal_Estudiante.html).

**2. Vista B: Inicio de Sesión Regular (Login Estándar)**

-   **Lógica de Renderizado (Frontend):** Si el estudiante ingresa a la ruta raíz (ej. adam.edu/login) sin parámetros en la URL, se renderiza la vista de Login tradicional.

-   **Autenticación:** El estudiante debe poder iniciar sesión ya sea a través del servicio Single Sign-On (Microsoft) o ingresando su Email Institucional y Contraseña.

-   **Políticas de Seguridad (Prevención de Enumeración):** Por directrices de seguridad, si el usuario ingresa credenciales inválidas, el backend debe retornar y el frontend debe mostrar un mensaje genérico de error (ej. *"Credenciales incorrectas"*). **Nunca** se debe revelar si el email ingresado existe o no en la base de datos.

-   **Delegación de Matrícula:** La UI debe incluir un *helper text* (texto de ayuda) indicando que, si el estudiante ya tiene una cuenta y recibió un código nuevo, debe iniciar sesión normalmente y utilizar el botón "Unirme a un curso" directamente desde su Dashboard interno.

-   **Redirección:** Tras autenticarse correctamente, el sistema redirige al estudiante a su panel principal para consumir la API de sus cursos vigentes (próxima feature).



## Portal Usuario Administrador de Universidad:

## Módulo: Portal administrador - Activación e Inicio de Sesión

**Descripción General del Módulo:** Este módulo maneja el acceso del perfil con mayores privilegios dentro de una institución educativa. Para esta versión de la plataforma, el flujo de entrada será mediante aprovisionamiento manual (cero fricciones de registro). El equipo interno de ADAM EDU creará las credenciales y se las entregará directamente al cliente.

**1. Creación de Cuenta (Flujo Interno - Backend)**

-   **Sin auto-registro:** No existirá ninguna vista pública en el Frontend (React) para que un Administrador de Universidad se registre.

-   **Aprovisionamiento Directo:** El equipo de Super Administradores de ADAM EDU creará el usuario directamente en la base de datos (mediante script o endpoint interno privado).

-   **Campos Obligatorios:** Al crear el usuario, el backend asignará inmediatamente el **Email Institucional**, una **Contraseña Genérica/Temporal** y, lo más importante, el **university_id** (para garantizar la arquitectura *Multi-tenant* y que el Admin solo vea los datos de su propia universidad).

**2. Inicio de Sesión (Login)**

-   **Acceso Directo:** El Administrador de la universidad recibirá sus credenciales (Email y Contraseña) por parte del equipo comercial/soporte de ADAM. Ingresará a la ruta de login de administradores (ej. adam.edu/admin/login) y digitará estas credenciales.

-   **Validación y Enrutamiento:** Una vez que el backend valida las credenciales y el rol (role: 'university_admin'), el Frontend de React debe redirigirlo automáticamente a su panel de control institucional (Dashboard del Administrador), desde donde podrá empezar a crear cursos e invitar profesores. C:\Users\Juan Camilo Dorado\Downloads\ADAM-EDU\docs\planPlataforma\Mockups\admin\Dashboard_admin.html

**Recurso UI (Mockup):** Dashboard_admin.html (Archivo base para maquetar las vistas y componentes en React). La ruta del mockup es esta: C:\Users\Juan Camilo Dorado\Downloads\ADAM-EDU\docs\planPlataforma\Mockups\admin\Dashboard_admin.html
