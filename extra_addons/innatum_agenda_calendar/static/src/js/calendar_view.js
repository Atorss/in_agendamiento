/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { deserializeDateTime, serializeDateTime } from "@web/core/l10n/dates";
import { _t } from "@web/core/l10n/translation";

// En Odoo 18 luxon NO es un módulo importable: se expone como global.
// El core lo usa así (ver web/static/src/core/l10n/dates.js).
const { DateTime } = luxon;

const MODEL = "innatum.agenda.turno";

// Rango horario por defecto de las vistas semana/día (se expande para que
// quepan los eventos que caigan fuera).
const DEFAULT_START_HOUR = 6;
const DEFAULT_END_HOUR = 22;
const HOUR_HEIGHT = 52; // px por hora en el timeline

// Granularidad para crear turnos al hacer click en un hueco (minutos).
const SLOT_MINUTES = 30;

// Metadatos por estado: etiqueta + clase CSS (color).
const STATE_META = {
    available: { label: _t("Disponible"), cls: "o_iac_state_available" },
    reserved: { label: _t("Reservado"), cls: "o_iac_state_reserved" },
    confirmed: { label: _t("Confirmado"), cls: "o_iac_state_confirmed" },
    done: { label: _t("Finalizado"), cls: "o_iac_state_done" },
    cancelled: { label: _t("Cancelado"), cls: "o_iac_state_cancelled" },
};

const WEEKDAY_SHORT = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"];

/**
 * Calendario interactivo de turnos (CalendarKit-like, nativo OWL).
 *
 * - Vistas mes / semana / día.
 * - Drag & drop para reagendar (escribe date_start; el core recalcula date_end
 *   y valida solapes).
 * - Click en hueco → crea turno (form del core en diálogo).
 * - Click en día → modal de agenda diaria en grande.
 * - Filtros por profesional / servicio / estado.
 *
 * No define modelos: lee/escribe vía el servicio ORM, así queda aislado del
 * resto de módulos de in_agendamiento.
 */
export class AgendaCalendar extends Component {
    static template = "innatum_agenda_calendar.Calendar";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.STATE_META = STATE_META;
        this.WEEKDAY_SHORT = WEEKDAY_SHORT;
        this.HOUR_HEIGHT = HOUR_HEIGHT;

        this.state = useState({
            view: "month", // month | week | day
            cursorISO: DateTime.now().toISODate(), // ancla de navegación
            events: [],
            professionals: [],
            servicios: [],
            filterProfessional: null,
            filterServicio: null,
            filterState: null,
            loading: true,
            // Modal de día
            dayModalISO: null,
            // arrastre en curso (id del turno)
            draggingId: null,
        });

        onWillStart(async () => {
            await this.loadFilters();
            await this.loadEvents();
        });
    }

    // ===================================================================
    // Fechas auxiliares
    // ===================================================================
    get cursor() {
        return DateTime.fromISO(this.state.cursorISO);
    }

    set cursor(dt) {
        this.state.cursorISO = dt.toISODate();
    }

    get today() {
        return DateTime.now().startOf("day");
    }

    /** Lunes de la semana del cursor. */
    get weekStart() {
        const c = this.cursor.startOf("day");
        return c.minus({ days: c.weekday - 1 });
    }

    /** Primer/último día del grid mensual (semanas completas lun→dom). */
    get monthGridStart() {
        const first = this.cursor.startOf("month");
        return first.minus({ days: first.weekday - 1 });
    }

    get monthGridEnd() {
        const last = this.cursor.endOf("month");
        return last.plus({ days: 7 - last.weekday }).endOf("day");
    }

    /** Rango [inicio, fin) que se debe cargar según la vista. */
    get rangeStart() {
        if (this.state.view === "month") {
            return this.monthGridStart;
        }
        if (this.state.view === "week") {
            return this.weekStart;
        }
        return this.cursor.startOf("day");
    }

    get rangeEnd() {
        if (this.state.view === "month") {
            return this.monthGridEnd;
        }
        if (this.state.view === "week") {
            return this.weekStart.plus({ days: 7 });
        }
        return this.cursor.startOf("day").plus({ days: 1 });
    }

    /** Etiqueta del periodo en la barra superior. */
    get periodLabel() {
        const c = this.cursor.setLocale("es");
        if (this.state.view === "month") {
            return c.toFormat("LLLL yyyy");
        }
        if (this.state.view === "day") {
            return c.toFormat("cccc d 'de' LLLL yyyy");
        }
        // week
        const s = this.weekStart.setLocale("es");
        const e = this.weekStart.plus({ days: 6 }).setLocale("es");
        return `${s.toFormat("d LLL")} – ${e.toFormat("d LLL yyyy")}`;
    }

    get rangeSubLabel() {
        const s = this.rangeStart.setLocale("es");
        const e = this.rangeEnd.minus({ days: 1 }).setLocale("es");
        return `${s.toFormat("d LLL yyyy")} – ${e.toFormat("d LLL yyyy")}`;
    }

    // ===================================================================
    // Carga de datos
    // ===================================================================
    async loadFilters() {
        // Profesionales que realmente tienen turnos (vía read_group).
        const groups = await this.orm.readGroup(
            MODEL,
            [],
            ["professional_id"],
            ["professional_id"]
        );
        this.state.professionals = groups
            .filter((g) => g.professional_id)
            .map((g) => ({ id: g.professional_id[0], name: g.professional_id[1] }));

        this.state.servicios = await this.orm.searchRead(
            "innatum.agenda.servicio",
            [],
            ["id", "name"],
            { order: "name" }
        );
    }

    get domain() {
        const dom = [
            ["date_start", "<", serializeDateTime(this.rangeEnd)],
            ["date_end", ">", serializeDateTime(this.rangeStart)],
        ];
        if (this.state.filterProfessional) {
            dom.push(["professional_id", "=", this.state.filterProfessional]);
        }
        if (this.state.filterServicio) {
            dom.push(["servicio_id", "=", this.state.filterServicio]);
        }
        if (this.state.filterState) {
            dom.push(["state", "=", this.state.filterState]);
        }
        return dom;
    }

    async loadEvents() {
        this.state.loading = true;
        try {
            const records = await this.orm.searchRead(MODEL, this.domain, [
                "name",
                "date_start",
                "date_end",
                "duration",
                "state",
                "professional_id",
                "partner_id",
                "servicio_id",
            ]);
            this.state.events = records.map((r) => this._normalize(r));
        } finally {
            this.state.loading = false;
        }
    }

    _normalize(r) {
        const start = deserializeDateTime(r.date_start);
        const end = r.date_end
            ? deserializeDateTime(r.date_end)
            : start.plus({ minutes: r.duration || SLOT_MINUTES });
        return {
            id: r.id,
            title: r.name || _t("Turno"),
            start,
            end,
            state: r.state,
            professionalId: r.professional_id ? r.professional_id[0] : null,
            professional: r.professional_id ? r.professional_id[1] : "",
            partner: r.partner_id ? r.partner_id[1] : "",
            servicio: r.servicio_id ? r.servicio_id[1] : "",
        };
    }

    // ===================================================================
    // Navegación / vista / filtros
    // ===================================================================
    setView(view) {
        this.state.view = view;
        this.loadEvents();
    }

    goToday() {
        this.cursor = DateTime.now();
        this.loadEvents();
    }

    _shift() {
        if (this.state.view === "month") {
            return { months: 1 };
        }
        if (this.state.view === "week") {
            return { weeks: 1 };
        }
        return { days: 1 };
    }

    prev() {
        this.cursor = this.cursor.minus(this._shift());
        this.loadEvents();
    }

    next() {
        this.cursor = this.cursor.plus(this._shift());
        this.loadEvents();
    }

    onFilterProfessional(ev) {
        const v = ev.target.value;
        this.state.filterProfessional = v ? parseInt(v, 10) : null;
        this.loadEvents();
    }

    onFilterServicio(ev) {
        const v = ev.target.value;
        this.state.filterServicio = v ? parseInt(v, 10) : null;
        this.loadEvents();
    }

    onFilterState(ev) {
        this.state.filterState = ev.target.value || null;
        this.loadEvents();
    }

    // ===================================================================
    // Helpers de presentación
    // ===================================================================
    /** Opciones de estado para el filtro (evita usar Object.keys en el template). */
    get stateOptions() {
        return Object.entries(STATE_META).map(([code, meta]) => ({
            code,
            label: meta.label,
        }));
    }

    stateLabel(state) {
        return (STATE_META[state] || {}).label || state;
    }

    stateClass(state) {
        return (STATE_META[state] || {}).cls || "";
    }

    fmtHour(dt) {
        return dt.setLocale("es").toFormat("HH:mm");
    }

    /** Texto completo para el atributo title (hover) de un evento. */
    tooltip(ev) {
        const range = `${this.fmtHour(ev.start)} – ${this.fmtHour(ev.end)}`;
        const who = [ev.professional, ev.partner, ev.servicio].filter(Boolean).join(" · ");
        return who ? `${range}  ${who}` : range;
    }

    /** Eventos (ya filtrados por el dominio del servidor) de un día concreto. */
    eventsForDay(dayDT) {
        const dayStart = dayDT.startOf("day");
        const dayEnd = dayStart.plus({ days: 1 });
        return this.state.events
            .filter((e) => e.start < dayEnd && e.end > dayStart)
            .sort((a, b) => a.start - b.start);
    }

    // ===================================================================
    // Vista MES
    // ===================================================================
    get monthWeeks() {
        const weeks = [];
        let day = this.monthGridStart;
        const end = this.monthGridEnd;
        const month = this.cursor.month;
        while (day < end) {
            const week = [];
            for (let i = 0; i < 7; i++) {
                const dayEvents = this.eventsForDay(day);
                week.push({
                    iso: day.toISODate(),
                    label: day.day,
                    inMonth: day.month === month,
                    isToday: day.hasSame(this.today, "day"),
                    events: dayEvents.slice(0, 3),
                    extra: Math.max(0, dayEvents.length - 3),
                });
                day = day.plus({ days: 1 });
            }
            weeks.push(week);
        }
        return weeks;
    }

    // ===================================================================
    // Vistas SEMANA / DÍA (timeline)
    // ===================================================================
    /** Días que muestra la vista actual (7 para semana, 1 para día). */
    get timelineDays() {
        if (this.state.view === "day") {
            return [this._dayColumn(this.cursor.startOf("day"))];
        }
        const days = [];
        for (let i = 0; i < 7; i++) {
            days.push(this._dayColumn(this.weekStart.plus({ days: i })));
        }
        return days;
    }

    _dayColumn(dayDT) {
        const events = this.eventsForDay(dayDT);
        return {
            iso: dayDT.toISODate(),
            weekdayShort: WEEKDAY_SHORT[dayDT.weekday - 1],
            dayNum: dayDT.day,
            isToday: dayDT.hasSame(this.today, "day"),
            layout: this._layout(events, dayDT),
        };
    }

    /** Rango horario visible (se expande si hay eventos fuera del default). */
    get hourRange() {
        let min = DEFAULT_START_HOUR;
        let max = DEFAULT_END_HOUR;
        for (const e of this.state.events) {
            if (this.state.view === "day" && !e.start.hasSame(this.cursor, "day")) {
                continue;
            }
            min = Math.min(min, e.start.hour);
            max = Math.max(max, Math.ceil(e.end.hour + e.end.minute / 60));
        }
        return { min: Math.max(0, min), max: Math.min(24, Math.max(max, min + 1)) };
    }

    get hours() {
        const { min, max } = this.hourRange;
        const out = [];
        for (let h = min; h < max; h++) {
            out.push(h);
        }
        return out;
    }

    get gridHeight() {
        const { min, max } = this.hourRange;
        return (max - min) * HOUR_HEIGHT;
    }

    /**
     * Calcula la posición de cada evento en una columna día, repartiendo en
     * carriles los que se solapan (overlap detection estilo CalendarKit).
     */
    _layout(events, dayDT) {
        const { min } = this.hourRange;
        const dayStart = dayDT.startOf("day");

        // Agrupar en clusters de solape y asignar columnas.
        const sorted = [...events].sort((a, b) => a.start - b.start || b.end - a.end);
        const positioned = [];
        let cluster = [];
        let clusterEnd = null;

        const flush = () => {
            const cols = [];
            for (const ev of cluster) {
                let placed = false;
                for (let c = 0; c < cols.length; c++) {
                    if (cols[c] <= ev.start) {
                        ev._col = c;
                        cols[c] = ev.end;
                        placed = true;
                        break;
                    }
                }
                if (!placed) {
                    ev._col = cols.length;
                    cols.push(ev.end);
                }
            }
            const total = cols.length;
            for (const ev of cluster) {
                positioned.push(this._position(ev, dayStart, min, ev._col, total));
            }
            cluster = [];
            clusterEnd = null;
        };

        for (const ev of sorted) {
            if (cluster.length && ev.start >= clusterEnd) {
                flush();
            }
            cluster.push(ev);
            clusterEnd = clusterEnd ? DateTime.max(clusterEnd, ev.end) : ev.end;
        }
        if (cluster.length) {
            flush();
        }
        return positioned;
    }

    _position(ev, dayStart, minHour, col, total) {
        // Recortar al día visible.
        const visStart = DateTime.max(ev.start, dayStart);
        const visEnd = DateTime.min(ev.end, dayStart.plus({ days: 1 }));
        const startMin = visStart.diff(dayStart, "minutes").minutes - minHour * 60;
        const durMin = Math.max(20, visEnd.diff(visStart, "minutes").minutes);
        const top = (startMin / 60) * HOUR_HEIGHT;
        const height = (durMin / 60) * HOUR_HEIGHT;
        const widthPct = 100 / total;
        return {
            ev,
            style:
                `top:${top}px;height:${height}px;` +
                `left:${col * widthPct}%;width:calc(${widthPct}% - 4px);`,
        };
    }

    // ===================================================================
    // Interacciones: abrir form, crear, modal de día
    // ===================================================================
    /** Abre el form view del core (en diálogo) para ver/editar un turno. */
    openEvent(id) {
        this.action.doAction(
            {
                type: "ir.actions.act_window",
                res_model: MODEL,
                res_id: id,
                views: [[false, "form"]],
                target: "new",
            },
            { onClose: () => this.loadEvents() }
        );
    }

    /** Crea un turno con valores por defecto (fecha y, si aplica, profesional). */
    createAt(dateTimeISO) {
        const ctx = {};
        if (dateTimeISO) {
            // serializeDateTime espera luxon; convertimos el ISO a UTC para el default.
            ctx.default_date_start = serializeDateTime(DateTime.fromISO(dateTimeISO));
        }
        if (this.state.filterProfessional) {
            ctx.default_professional_id = this.state.filterProfessional;
        }
        this.action.doAction(
            {
                type: "ir.actions.act_window",
                res_model: MODEL,
                views: [[false, "form"]],
                target: "new",
                context: ctx,
            },
            { onClose: () => this.loadEvents() }
        );
    }

    /** Click en un día del grid mensual → abre el modal de día. */
    openDay(iso) {
        this.state.dayModalISO = iso;
    }

    /** Click en el área vacía de una celda del mes → crear turno ese día.
     *  El día queda prellenado (09:00 por defecto); el usuario ajusta la hora. */
    onCreateDay(iso) {
        this.createAt(`${iso}T09:00:00`);
    }

    closeDayModal() {
        this.state.dayModalISO = null;
    }

    get dayModal() {
        if (!this.state.dayModalISO) {
            return null;
        }
        const dt = DateTime.fromISO(this.state.dayModalISO).setLocale("es");
        return {
            iso: this.state.dayModalISO,
            title: dt.toFormat("cccc d 'de' LLLL yyyy"),
            events: this.eventsForDay(dt),
        };
    }

    /** Crear desde el modal de día (a las 9:00 por defecto). */
    createInDay() {
        const dt = DateTime.fromISO(this.state.dayModalISO).set({ hour: 9, minute: 0 });
        this.closeDayModal();
        this.createAt(dt.toISO());
    }

    /** Click en un hueco horario de la vista semana/día. */
    onSlotClick(dayISO, hour) {
        const dt = DateTime.fromISO(dayISO).set({ hour, minute: 0 });
        this.createAt(dt.toISO());
    }

    // ===================================================================
    // Drag & drop (reagendar)
    // ===================================================================
    onDragStart(ev, id) {
        this.state.draggingId = id;
        if (ev.dataTransfer) {
            ev.dataTransfer.effectAllowed = "move";
            ev.dataTransfer.setData("text/plain", String(id));
        }
    }

    onDragEnd() {
        this.state.draggingId = null;
    }

    onDragOver(ev) {
        ev.preventDefault();
        if (ev.dataTransfer) {
            ev.dataTransfer.dropEffect = "move";
        }
    }

    /** Drop en un día del grid mensual: conserva la hora, cambia la fecha. */
    async onDropDay(ev, dayISO) {
        ev.preventDefault();
        const id = this.state.draggingId;
        if (!id) {
            return;
        }
        const evt = this.state.events.find((e) => e.id === id);
        if (!evt) {
            return;
        }
        const target = DateTime.fromISO(dayISO).set({
            hour: evt.start.hour,
            minute: evt.start.minute,
        });
        await this._reschedule(id, target);
    }

    /** Drop en la rejilla de un día (semana/día): calcula hora desde la Y. */
    async onDropTimeline(ev, dayISO) {
        ev.preventDefault();
        const id = this.state.draggingId;
        if (!id) {
            return;
        }
        const rect = ev.currentTarget.getBoundingClientRect();
        const y = ev.clientY - rect.top;
        const { min } = this.hourRange;
        let minutes = min * 60 + (y / HOUR_HEIGHT) * 60;
        // Redondear a la granularidad.
        minutes = Math.round(minutes / SLOT_MINUTES) * SLOT_MINUTES;
        const target = DateTime.fromISO(dayISO)
            .startOf("day")
            .plus({ minutes });
        await this._reschedule(id, target);
    }

    async _reschedule(id, targetStart) {
        this.state.draggingId = null;
        try {
            await this.orm.write(MODEL, [id], {
                date_start: serializeDateTime(targetStart),
            });
            this.notification.add(_t("Turno reagendado"), { type: "success" });
        } catch (e) {
            // El core valida solapes; mostramos el error y recargamos para revertir.
            this.notification.add(
                e.data && e.data.message ? e.data.message : _t("No se pudo reagendar el turno"),
                { type: "danger" }
            );
        }
        await this.loadEvents();
    }
}

registry.category("actions").add("innatum_agenda_calendar.calendar", AgendaCalendar);
