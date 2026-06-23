/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";

/**
 * Bandeja de Sesiones WhatsApp estilo Chatwoot (solo lectura).
 *
 * Layout de 3 columnas:
 *   - Izquierda: lista de conversaciones (innatum.ai.session).
 *   - Centro: hilo de mensajes de la conversación seleccionada.
 *   - Derecha: ficha de contacto + datos de la conversación.
 *
 * Los datos se piden a métodos del modelo (inbox_conversations / inbox_detail)
 * para que las record rules de company scopeen el resultado al tenant.
 */
export class WhatsappInbox extends Component {
    static template = "innatum_agenda_ai.WhatsappInbox";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            conversations: [],
            filter: "all",          // all | active | handoff
            search: "",
            activeId: null,
            detail: null,
            loadingList: true,
            loadingDetail: false,
        });

        onWillStart(async () => {
            await this.loadConversations();
        });
    }

    // ----- Carga de datos -------------------------------------------------
    get domain() {
        if (this.state.filter === "handoff") {
            return [["state", "=", "con_humano"]];
        }
        if (this.state.filter === "active") {
            return [["state", "not in", ["cancelada", "realizada", "expirada"]]];
        }
        return [];
    }

    async loadConversations() {
        this.state.loadingList = true;
        try {
            this.state.conversations = await this.orm.call(
                "innatum.ai.session",
                "inbox_conversations",
                [this.domain]
            );
        } finally {
            this.state.loadingList = false;
        }
    }

    async openConversation(id) {
        if (this.state.activeId === id) {
            return;
        }
        this.state.activeId = id;
        this.state.loadingDetail = true;
        try {
            this.state.detail = await this.orm.call(
                "innatum.ai.session",
                "inbox_detail",
                [id]
            );
        } finally {
            this.state.loadingDetail = false;
        }
    }

    // ----- Filtros / búsqueda --------------------------------------------
    async setFilter(filter) {
        this.state.filter = filter;
        await this.loadConversations();
    }

    get visibleConversations() {
        const q = this.state.search.trim().toLowerCase();
        if (!q) {
            return this.state.conversations;
        }
        return this.state.conversations.filter(
            (c) =>
                c.wa_from.toLowerCase().includes(q) ||
                (c.partner_name || "").toLowerCase().includes(q) ||
                (c.last_preview || "").toLowerCase().includes(q)
        );
    }

    // ----- Helpers de presentación ---------------------------------------
    title(c) {
        return c.partner_name || c.wa_from || "Sin identificar";
    }

    initials(c) {
        const t = this.title(c).trim();
        return t ? t.charAt(0).toUpperCase() : "?";
    }

    /** "2026-06-22 14:03:00" -> "22 jun, 14:03" (o solo hora si es hoy). */
    formatDate(value) {
        if (!value) {
            return "";
        }
        const d = new Date(value.replace(" ", "T"));
        if (isNaN(d.getTime())) {
            return value;
        }
        const opts = { hour: "2-digit", minute: "2-digit" };
        const now = new Date();
        if (d.toDateString() !== now.toDateString()) {
            opts.day = "2-digit";
            opts.month = "short";
        }
        return d.toLocaleString(undefined, opts);
    }

    isOutbound(role) {
        // El agente / sistema se pinta a la derecha; el cliente a la izquierda.
        return role === "assistant" || role === "system";
    }

    roleLabel(role) {
        return {
            user: "Cliente",
            assistant: "Agente IA",
            system: "Sistema",
            tool: "Tool",
        }[role] || role;
    }
}

registry.category("actions").add("innatum_agenda_ai.whatsapp_inbox", WhatsappInbox);
