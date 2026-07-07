/** @odoo-module **/

/*
 * Pinta el fondo del calendario según el horario laboral del profesional
 * logueado (su resource.calendar). Las franjas fuera de su jornada quedan
 * sombreadas (gris tenue, clase .fc-non-business de FullCalendar) y las horas
 * que trabaja quedan en blanco. Así se ve de un vistazo qué días y de qué hora
 * a qué hora atiende.
 *
 * Solo aplica a los calendarios de Turnos y Bloqueos (por resModel). El
 * horario se obtiene del backend (get_business_hours_usuario) en formato
 * FullCalendar y se inyecta con setOption('businessHours', ...) una vez que la
 * instancia de FullCalendar ya está montada.
 */

import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { CalendarCommonRenderer } from "@web/views/calendar/calendar_common/calendar_common_renderer";
import { onWillStart, onMounted } from "@odoo/owl";

// Modelos cuyos calendarios deben mostrar el horario laboral de fondo.
const MODELOS_CON_HORARIO = [
    "innatum.agenda.turno",
    "innatum.agenda.bloqueo",
    "innatum.agenda.turno.propuesta", // selector de horario de un turno
];
// Modelo donde vive el método backend (siempre accesible para el rol usuario).
const MODELO_HOST = "innatum.agenda.turno";

patch(CalendarCommonRenderer.prototype, {
    setup() {
        super.setup();
        if (!MODELOS_CON_HORARIO.includes(this.props.model.resModel)) {
            return;
        }
        this.innatumOrm = useService("orm");
        this.innatumBusinessHours = false;

        onWillStart(async () => {
            // En el selector de horario (modelo propuesta), el fondo debe ser
            // el del PROFESIONAL DEL TURNO, no el del usuario logueado. El turno
            // viene en el contexto de la acción como default_derivacion_id.
            let turnoId = null;
            if (this.props.model.resModel === "innatum.agenda.turno.propuesta") {
                turnoId = this.props.model.meta.context?.default_derivacion_id || null;
            }
            try {
                this.innatumBusinessHours = await this.innatumOrm.call(
                    MODELO_HOST,
                    "get_business_hours_usuario",
                    [turnoId]
                );
            } catch {
                this.innatumBusinessHours = false;
            }
        });

        // Se aplica DESPUÉS de que useFullCalendar creó la instancia (su
        // onMounted se registró antes que este). Para week/day/month la
        // instancia persiste, así que basta setearlo una vez.
        onMounted(() => {
            if (this.innatumBusinessHours && this.innatumBusinessHours.length && this.fc?.api) {
                this.fc.api.setOption("businessHours", this.innatumBusinessHours);
            }
        });
    },
});
