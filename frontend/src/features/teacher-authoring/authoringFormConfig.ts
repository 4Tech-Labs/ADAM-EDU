export const professorDB = {
    courses: [
        {
            id: "course_001",
            name: "Gerencia Estratégica y Modelos de Negocio",
            level: "Especialización",
            activeGroups: ["Grupo 01 (Lun)", "Grupo 02 (Mar)"],
            syllabus: [
                {
                    id: "m1",
                    name: "Módulo 1: Fundamentos de Estrategia",
                    units: [
                        { id: "u1.1", name: "1.1 Evolución Estratégica Digital" },
                        { id: "u1.2", name: "1.2 Efectos de Red y Plataformas" },
                        { id: "u1.3", name: "1.3 DAOs" },
                    ],
                },
                {
                    id: "m2",
                    name: "Módulo 2: IA Generativa y Agéntica",
                    units: [
                        { id: "u2.1", name: "2.1 Fundamentos de GenAI" },
                        { id: "u2.2", name: "2.2 IA Agéntica Organizacional" },
                    ],
                },
            ],
        },
        {
            id: "course_002",
            name: "Arquitectura Empresarial",
            level: "Maestría",
            activeGroups: ["Grupo 01 (Mié)", "Grupo Virtual"],
            syllabus: [
                {
                    id: "m1_arch",
                    name: "Módulo 1: Frameworks TOGAF",
                    units: [{ id: "u1a", name: "1.1 Introducción" }],
                },
            ],
        },
    ],
};

export const INDUSTRIAS_OPTIONS = [
    { value: "retail", label: "Retail & E-commerce" },
    { value: "fintech", label: "FinTech & Banca" },
    { value: "salud", label: "Salud & Medicina" },
    { value: "logistica", label: "Logística & Supply Chain" },
    { value: "educacion", label: "Educación" },
    { value: "telecomunicaciones", label: "Telecomunicaciones" },
    { value: "manufactura", label: "Manufactura" },
];

export const STUDENT_PROFILES = [
    { value: "business", label: "Negocios / Gestión" },
    { value: "ml_ds", label: "Machine Learning / Data Science" },
];

export const FORM_STYLES = `
.teacher-form .input-base {
  transition: border-color 0.18s, box-shadow 0.18s;
  outline: none;
}
.teacher-form .input-base:focus {
  border-color: var(--adam-brand);
  box-shadow: 0 0 0 3px rgba(1, 68, 160, 0.12);
}
.teacher-form .input-base:hover:not(:focus):not(:disabled) {
  border-color: #94a3b8;
}
.teacher-form .input-base:read-only, .teacher-form .input-base:disabled {
  background-color: #f8fafc;
  color: #64748b;
  cursor: not-allowed;
  border-color: #e2e8f0;
}
.teacher-form .input-error {
  border-color: var(--adam-error) !important;
  box-shadow: 0 0 0 3px rgba(239, 68, 68, 0.10) !important;
}
.teacher-form .step-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--adam-brand);
  color: #fff;
  font-size: 15px;
  font-weight: 800;
  flex-shrink: 0;
  letter-spacing: -0.3px;
  box-shadow: 0 2px 8px rgba(1, 68, 160, 0.30);
}
.teacher-form .scope-card {
  transition: border-color 0.18s, background-color 0.18s, box-shadow 0.18s;
  border: 1.5px solid #e2e8f0;
  border-radius: 12px;
  background: #fff;
  cursor: pointer;
  position: relative;
}
.teacher-form .scope-card:hover:not(.active) {
  border-color: #94a3b8;
  background: #f8fafc;
}
.teacher-form .scope-card.active {
  border-color: var(--adam-brand);
  background: var(--adam-brand-light);
  box-shadow: 0 0 0 1px var(--adam-brand);
}
.teacher-form .scope-check {
  display: none;
  position: absolute;
  top: 10px;
  right: 10px;
  width: 18px;
  height: 18px;
  background: var(--adam-brand);
  border-radius: 50%;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 10px;
}
.teacher-form .scope-card.active .scope-check {
  display: flex;
}
.teacher-form .chip {
  animation: chipPop 0.18s cubic-bezier(0.4, 0, 0.2, 1) both;
}
@keyframes chipPop {
  from { transform: scale(0.85); opacity: 0; }
  to { transform: scale(1); opacity: 1; }
}
.teacher-form .chip-warning {
  font-size: 11px;
  color: #92400e;
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 6px;
  padding: 4px 10px;
  margin-top: 6px;
  width: fit-content;
}
.teacher-form .section-divider {
  position: relative;
  border: none;
}
.teacher-form .section-divider::after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 1.5px;
  background: linear-gradient(to right, #0144a0 0%, #93c5fd 55%, transparent 100%);
  border-radius: 2px;
}
.teacher-form .footer-divider {
  border: none;
  height: 1.5px;
  background: linear-gradient(to right, transparent 0%, #bfdbfe 25%, #0144a0 50%, #bfdbfe 75%, transparent 100%);
  border-radius: 2px;
}
.teacher-form .field-hint {
  font-size: 11.5px;
  color: #64748b;
  margin-top: 5px;
  line-height: 1.4;
}
.teacher-form .fade-in-up {
  animation: fadeInUp 0.45s ease-out both;
}
@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(18px); }
  to { opacity: 1; transform: translateY(0); }
}
.teacher-form .date-arrow {
  display: flex;
  align-items: center;
  justify-content: center;
  color: #94a3b8;
  padding-top: 30px;
}
`;
