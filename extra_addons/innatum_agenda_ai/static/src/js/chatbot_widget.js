/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";

publicWidget.registry.InnatumChatbot = publicWidget.Widget.extend({
    selector: '#innatum-chatbot-root',

    start() {
        this._super.apply(this, arguments);
        this.token = null;
        this.isOpen = false;
        this.isLoading = false;
        this.isRecording = false;
        this._mediaRecorder = null;
        this._audioChunks = [];
        this.sessionState = null; // 'pending_id' | 'active' | 'done'
        this._buildWidget();
    },

    // =============================================
    // Build DOM
    // =============================================

    _buildWidget() {
        this.btnEl = this._createElement('button', 'inmed-cb-btn', `
            <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
            </svg>
        `);
        this.btnEl.title = 'Reservar turno';
        this.btnEl.addEventListener('click', () => this._toggle());

        this.panelEl = this._createElement('div', 'inmed-cb-panel inmed-cb-hidden');
        this.panelEl.innerHTML = `
            <div class="inmed-cb-header">
                <div class="inmed-cb-header-info">
                    <div class="inmed-cb-avatar">
                        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M22 12h-4l-3 9L9 3l-3 9H2"/>
                        </svg>
                    </div>
                    <div>
                        <div class="inmed-cb-title">Asistente Virtual</div>
                        <div class="inmed-cb-subtitle">Reserva de turnos</div>
                    </div>
                </div>
                <button class="inmed-cb-close" title="Cerrar">
                    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2">
                        <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                    </svg>
                </button>
            </div>
            <div class="inmed-cb-messages"></div>
            <div class="inmed-cb-input-area">
                <textarea class="inmed-cb-input" placeholder="Ingresa tu identificación..." rows="1"></textarea>
                <button class="inmed-cb-mic" title="Grabar mensaje de voz">
                    <svg class="inmed-cb-mic-icon" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <rect x="9" y="1" width="6" height="12" rx="3"/>
                        <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
                        <line x1="12" y1="19" x2="12" y2="23"/>
                        <line x1="8" y1="23" x2="16" y2="23"/>
                    </svg>
                    <svg class="inmed-cb-stop-icon" viewBox="0 0 24 24" width="20" height="20" fill="currentColor" style="display:none">
                        <rect x="6" y="6" width="12" height="12" rx="2"/>
                    </svg>
                </button>
                <button class="inmed-cb-send" disabled title="Enviar">
                    <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
                        <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
                    </svg>
                </button>
            </div>
        `;

        this.messagesEl = this.panelEl.querySelector('.inmed-cb-messages');
        this.inputEl = this.panelEl.querySelector('.inmed-cb-input');
        this.sendBtn = this.panelEl.querySelector('.inmed-cb-send');
        this.micBtn = this.panelEl.querySelector('.inmed-cb-mic');
        this.closeBtn = this.panelEl.querySelector('.inmed-cb-close');

        this.closeBtn.addEventListener('click', () => this._toggle());
        this.sendBtn.addEventListener('click', () => this._handleSend());
        this.micBtn.addEventListener('click', () => this._toggleRecording());
        this.inputEl.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this._handleSend();
            }
        });
        this.inputEl.addEventListener('input', () => this._onInputChange());

        this.el.appendChild(this.panelEl);
        this.el.appendChild(this.btnEl);
    },

    // =============================================
    // Toggle
    // =============================================

    _toggle() {
        if (this.isOpen) {
            this.panelEl.classList.add('inmed-cb-hidden');
            this.btnEl.classList.remove('inmed-cb-btn-active');
        } else {
            this.panelEl.classList.remove('inmed-cb-hidden');
            this.btnEl.classList.add('inmed-cb-btn-active');
            if (!this.token) {
                this._initSession();
            }
            setTimeout(() => this.inputEl.focus(), 300);
        }
        this.isOpen = !this.isOpen;
    },

    // =============================================
    // Session Init
    // =============================================

    async _initSession() {
        this._showTyping();
        try {
            const result = await rpc('/chatbot/start', {});
            this._hideTyping();
            if (result.success) {
                this.token = result.token;
                this.sessionState = result.state; // 'pending_id'
                // Título del widget = nombre del agente (mismo bot_name de WhatsApp)
                if (result.agent_name) {
                    const titleEl = this.panelEl.querySelector('.inmed-cb-title');
                    if (titleEl) {
                        titleEl.textContent = result.agent_name;
                    }
                }
                this._addMessage('assistant', result.welcome_message);
                this.inputEl.placeholder = 'Ingresa tu identificación...';
            } else {
                this._addMessage('assistant', result.error || 'No se pudo conectar.');
            }
        } catch (err) {
            this._hideTyping();
            this._addMessage('assistant', 'Error al conectar. Intenta más tarde.');
        }
    },

    // =============================================
    // Handle Send (router según estado)
    // =============================================

    _handleSend() {
        if (this.sessionState === 'pending_id') {
            this._verifyCedula();
        } else if (this.sessionState === 'active') {
            this._sendMessage();
        }
    },

    // =============================================
    // Verify Cédula (sin tokens IA)
    // =============================================

    async _verifyCedula() {
        const cedula = this.inputEl.value.trim();
        if (!cedula || this.isLoading) return;

        this._addMessage('user', cedula);
        this.inputEl.value = '';
        this._onInputChange();

        this.isLoading = true;
        this.sendBtn.disabled = true;
        this._showTyping();

        try {
            const result = await rpc('/chatbot/verify', {
                token: this.token,
                cedula: cedula,
            });

            this._hideTyping();
            this.isLoading = false;

            if (result.success && result.found) {
                this.sessionState = 'active';
                this._addMessage('assistant', result.message);
                if (result.especialidades && result.especialidades.length > 0) {
                    this._renderOptionButtons(result.especialidades, 'especialidad');
                }
                this.inputEl.placeholder = 'Escribe tu mensaje...';
            } else if (result.success && result.needs_register) {
                // Cliente no encontrado — preguntar si quiere registrarse
                this.sessionState = 'pending_register';
                this._addMessage('assistant', result.message);
                this._showRegisterConfirm(result.has_account, result.vat);
            } else {
                // Error
                this._addMessage('assistant', result.error || 'No se pudo verificar.');
                this._showFormLink();
            }
        } catch (err) {
            this._hideTyping();
            this.isLoading = false;
            this._addMessage('assistant', 'Error de conexión. Intenta de nuevo.');
        }

        this._onInputChange();
    },

    _showFormLink() {
        const wrapper = this._createElement('div', 'inmed-cb-session-end');
        const btn = this._createElement('a', 'inmed-cb-restart-btn');
        btn.textContent = 'Ir al formulario de registro';
        btn.href = '/citas';
        btn.target = '_self';
        wrapper.appendChild(btn);

        const retryBtn = this._createElement('button', 'inmed-cb-restart-btn');
        retryBtn.textContent = 'Intentar otra cédula';
        retryBtn.style.marginLeft = '8px';
        retryBtn.addEventListener('click', () => {
            wrapper.remove();
            this.inputEl.focus();
        });
        wrapper.appendChild(retryBtn);

        this.messagesEl.appendChild(wrapper);
        this._scrollToBottom();
    },

    // =============================================
    // Option Buttons (Servicioes / Profesionales)
    // =============================================

    _renderOptionButtons(options, type) {
        const container = this._createElement('div', 'inmed-cb-options-container');
        for (const opt of options) {
            const btn = this._createElement('button', 'inmed-cb-option-btn');
            btn.textContent = opt.name;
            btn.addEventListener('click', () => {
                container.querySelectorAll('.inmed-cb-option-btn').forEach(b => {
                    b.disabled = true;
                    b.classList.add('inmed-cb-option-disabled');
                });
                btn.classList.add('inmed-cb-option-selected');
                this._addMessage('user', opt.name);
                this._executeAction('select_specialty', { code: opt.code });
            });
            container.appendChild(btn);
        }
        this.messagesEl.appendChild(container);
        this._scrollToBottom();
    },

    _renderProfesionalButtons(professionals, specialtyCode) {
        const container = this._createElement('div', 'inmed-cb-options-container');
        for (const doc of professionals) {
            const label = doc.nombre + (doc.consultorio ? ` - ${doc.consultorio}` : '');
            const btn = this._createElement('button', 'inmed-cb-option-btn inmed-cb-option-professional');
            btn.innerHTML = `
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>
                </svg>
                <span>${this._escapeHtml(label)}</span>
            `;
            btn.addEventListener('click', () => {
                container.querySelectorAll('.inmed-cb-option-btn').forEach(b => {
                    b.disabled = true;
                    b.classList.add('inmed-cb-option-disabled');
                });
                btn.classList.add('inmed-cb-option-selected');
                this._addMessage('user', doc.nombre);
                this._executeAction('select_professional', {
                    name: doc.nombre,
                    specialty_code: specialtyCode,
                });
            });
            container.appendChild(btn);
        }
        this.messagesEl.appendChild(container);
        this._scrollToBottom();
    },

    // =============================================
    // Action Executor (sin IA — lógica directa)
    // =============================================

    async _executeAction(action, params) {
        if (this.isLoading) return;

        this.isLoading = true;
        this.sendBtn.disabled = true;
        this._showTyping();

        try {
            const result = await rpc('/chatbot/action', {
                token: this.token,
                action: action,
                ...params,
            });

            this._hideTyping();
            this.isLoading = false;

            if (result.success) {
                const ui = result.ui || {};
                this._addMessage('assistant', result.response);

                if (ui.especialidades && ui.especialidades.length > 0) {
                    this._renderOptionButtons(ui.especialidades, 'especialidad');
                }
                if (ui.professionals && ui.professionals.length > 1) {
                    this._renderProfesionalButtons(ui.professionals, ui.specialty_code);
                }
                if (ui.slots && ui.slots.length > 0) {
                    this._renderSlotCards(ui.slots, ui.especialidad);
                }
                if (ui.booking) {
                    this._renderBookingCard(ui.booking);
                }
                if (ui.cambiar_cliente) {
                    this.sessionState = 'pending_id';
                    this.inputEl.placeholder = 'Ingresa tu identificación...';
                }
                if (result.session_state === 'done') {
                    this.sessionState = 'done';
                    this._showSessionEnded();
                }
            } else {
                if (result.error === 'session_expired') {
                    this.token = null;
                    this._showSessionEnded();
                } else {
                    this._addMessage('assistant', result.error || 'Error al procesar.');
                }
            }
        } catch (err) {
            this._hideTyping();
            this.isLoading = false;
            this._addMessage('assistant', 'Error de conexión. Intenta de nuevo.');
        }

        this._onInputChange();
    },

    // =============================================
    // Send Message (con IA, solo si state=active)
    // =============================================

    async _sendMessage(overrideText) {
        const text = overrideText || this.inputEl.value.trim();
        if (!text || this.isLoading) return;

        if (!overrideText) {
            this._addMessage('user', text);
        }
        this.inputEl.value = '';
        this.inputEl.style.height = 'auto';
        this._onInputChange();

        if (!this.token) {
            this._addMessage('assistant', 'Sesión no activa. Recarga la página.');
            return;
        }

        this.isLoading = true;
        this.sendBtn.disabled = true;
        this._showTyping();

        try {
            const result = await rpc('/chatbot/send', {
                token: this.token,
                message: text,
            });

            this._hideTyping();
            this.isLoading = false;

            if (result.success) {
                const ui = result.ui || {};
                this._addMessage('assistant', result.response);

                if (ui.especialidades && ui.especialidades.length > 0) {
                    this._renderOptionButtons(ui.especialidades, 'especialidad');
                }
                if (ui.professionals && ui.professionals.length > 1) {
                    this._renderProfesionalButtons(ui.professionals, ui.specialty_code || '');
                }
                if (ui.slots && ui.slots.length > 0) {
                    this._renderSlotCards(ui.slots, ui.especialidad);
                }
                if (ui.booking) {
                    this._renderBookingCard(ui.booking);
                }
                if (ui.cambiar_cliente) {
                    this.sessionState = 'pending_id';
                    this.inputEl.placeholder = 'Ingresa tu identificación...';
                }
                if (result.session_state === 'done') {
                    this.sessionState = 'done';
                    this._showSessionEnded();
                }
            } else {
                if (result.error === 'session_expired') {
                    this.token = null;
                    this._showSessionEnded();
                } else {
                    this._addMessage('assistant', result.error || 'Error al procesar.');
                }
            }
        } catch (err) {
            this._hideTyping();
            this.isLoading = false;
            this._addMessage('assistant', 'Error de conexión. Intenta de nuevo.');
        }

        this._onInputChange();
    },

    // =============================================
    // Message Rendering
    // =============================================

    _addMessage(role, text) {
        const msgEl = this._createElement('div', `inmed-cb-msg inmed-cb-msg-${role}`);
        const bubbleEl = this._createElement('div', 'inmed-cb-bubble');
        bubbleEl.innerHTML = this._formatText(text);
        const timeEl = this._createElement('div', 'inmed-cb-time');
        timeEl.textContent = new Date().toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' });
        msgEl.appendChild(bubbleEl);
        msgEl.appendChild(timeEl);
        this.messagesEl.appendChild(msgEl);
        this._scrollToBottom();
    },

    // =============================================
    // Slot Cards
    // =============================================

    _renderSlotCards(slots, especialidad) {
        const grouped = {};
        for (const slot of slots) {
            const key = slot.professional;
            if (!grouped[key]) grouped[key] = {};
            if (!grouped[key][slot.fecha]) grouped[key][slot.fecha] = [];
            grouped[key][slot.fecha].push(slot);
        }

        const container = this._createElement('div', 'inmed-cb-slots-container');
        for (const [professional, dates] of Object.entries(grouped)) {
            const card = this._createElement('div', 'inmed-cb-slot-card');
            const header = this._createElement('div', 'inmed-cb-slot-header');
            header.innerHTML = `
                <div class="inmed-cb-slot-professional">
                    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>
                    </svg>
                    <span>${this._escapeHtml(professional)}</span>
                </div>
                <div class="inmed-cb-slot-specialty">${this._escapeHtml(especialidad || '')}</div>
            `;
            card.appendChild(header);

            for (const [fecha, slotsInDate] of Object.entries(dates)) {
                const dateGroup = this._createElement('div', 'inmed-cb-slot-date-group');
                const dateLabel = this._createElement('div', 'inmed-cb-slot-date-label');
                dateLabel.innerHTML = `
                    <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2">
                        <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
                        <line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/>
                        <line x1="3" y1="10" x2="21" y2="10"/>
                    </svg>
                    <span>${this._escapeHtml(fecha)}</span>
                `;
                dateGroup.appendChild(dateLabel);
                const pillsWrap = this._createElement('div', 'inmed-cb-slot-pills');
                for (const s of slotsInDate) {
                    const pill = this._createElement('button', 'inmed-cb-slot-pill');
                    pill.innerHTML = `
                        <span class="inmed-cb-pill-time">${this._escapeHtml(s.hora)}</span>
                        <span class="inmed-cb-pill-dur">${s.duracion_min}min</span>
                    `;
                    pill.addEventListener('click', () => this._onSlotSelected(s, professional));
                    pillsWrap.appendChild(pill);
                }
                dateGroup.appendChild(pillsWrap);
                card.appendChild(dateGroup);
            }
            container.appendChild(card);
        }
        this.messagesEl.appendChild(container);
        this._scrollToBottom();
    },

    _onSlotSelected(slot, professional) {
        // Deshabilitar todas las pills
        this.messagesEl.querySelectorAll('.inmed-cb-slot-pill').forEach(p => {
            p.disabled = true;
            p.classList.add('inmed-cb-pill-disabled');
        });

        // Mostrar confirmación con botones
        this._showConfirmation(slot, professional);
    },

    _showConfirmation(slot, professional) {
        const card = this._createElement('div', 'inmed-cb-confirm-card');
        card.innerHTML = `
            <div class="inmed-cb-confirm-title">Confirmar turno</div>
            <div class="inmed-cb-confirm-details">
                <div class="inmed-cb-confirm-row"><strong>Profesional:</strong> ${this._escapeHtml(professional)}</div>
                <div class="inmed-cb-confirm-row"><strong>Fecha:</strong> ${this._escapeHtml(slot.fecha)}</div>
                <div class="inmed-cb-confirm-row"><strong>Hora:</strong> ${this._escapeHtml(slot.hora)}</div>
                <div class="inmed-cb-confirm-row"><strong>Duración:</strong> ${slot.duracion_min} min</div>
            </div>
            <div class="inmed-cb-confirm-question">¿Deseas confirmar este turno?</div>
            <div class="inmed-cb-confirm-buttons"></div>
        `;

        const btnWrap = card.querySelector('.inmed-cb-confirm-buttons');

        const btnYes = this._createElement('button', 'inmed-cb-confirm-btn inmed-cb-confirm-yes');
        btnYes.textContent = 'Confirmar';
        btnYes.addEventListener('click', () => {
            card.remove();
            this._addMessage('user', `${slot.fecha} a las ${slot.hora} con ${professional}`);
            this._executeAction('confirm_slot', {
                turno_id: slot.turno_id,
                servicio_codigo: slot.servicio_codigo || '',
            });
        });

        const btnNo = this._createElement('button', 'inmed-cb-confirm-btn inmed-cb-confirm-no');
        btnNo.textContent = 'Cancelar';
        btnNo.addEventListener('click', () => {
            card.remove();
            this._addMessage('assistant', 'No hay problema. Puedes seleccionar otro horario o buscar otra disponibilidad.');
            // Reactivar pills
            this.messagesEl.querySelectorAll('.inmed-cb-slot-pill').forEach(p => {
                p.disabled = false;
                p.classList.remove('inmed-cb-pill-disabled');
            });
        });

        btnWrap.appendChild(btnYes);
        btnWrap.appendChild(btnNo);
        this.messagesEl.appendChild(card);
        this._scrollToBottom();
    },

    // =============================================
    // Booking Card
    // =============================================

    _renderBookingCard(booking) {
        const card = this._createElement('div', 'inmed-cb-booking-card');
        card.innerHTML = `
            <div class="inmed-cb-booking-icon">
                <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
                    <polyline points="22 4 12 14.01 9 11.01"/>
                </svg>
            </div>
            <div class="inmed-cb-booking-title">Turno Reservado</div>
            <div class="inmed-cb-booking-ref">${this._escapeHtml(booking.referencia || '')}</div>
            <div class="inmed-cb-booking-details">
                <div class="inmed-cb-booking-row"><span class="inmed-cb-booking-label">Servicio</span><span class="inmed-cb-booking-value">${this._escapeHtml(booking.especialidad || '')}</span></div>
                <div class="inmed-cb-booking-row"><span class="inmed-cb-booking-label">Profesional</span><span class="inmed-cb-booking-value">${this._escapeHtml(booking.professional || '')}</span></div>
                <div class="inmed-cb-booking-row"><span class="inmed-cb-booking-label">Fecha</span><span class="inmed-cb-booking-value">${this._escapeHtml(booking.fecha || '')}</span></div>
                <div class="inmed-cb-booking-row"><span class="inmed-cb-booking-label">Hora</span><span class="inmed-cb-booking-value">${this._escapeHtml(booking.hora || '')}</span></div>
                <div class="inmed-cb-booking-row"><span class="inmed-cb-booking-label">Cliente</span><span class="inmed-cb-booking-value">${this._escapeHtml(booking.paciente || '')}</span></div>
            </div>
            <div class="inmed-cb-booking-status">Pendiente de confirmación</div>
        `;
        this.messagesEl.appendChild(card);
        this._scrollToBottom();
    },

    // =============================================
    // Typing & Session End
    // =============================================

    _showTyping() {
        if (this._typingEl) return;
        this._typingEl = this._createElement('div', 'inmed-cb-msg inmed-cb-msg-assistant inmed-cb-typing-wrap');
        this._typingEl.innerHTML = `<div class="inmed-cb-bubble inmed-cb-typing"><span class="inmed-cb-dot"></span><span class="inmed-cb-dot"></span><span class="inmed-cb-dot"></span></div>`;
        this.messagesEl.appendChild(this._typingEl);
        this._scrollToBottom();
    },

    _hideTyping() {
        if (this._typingEl) { this._typingEl.remove(); this._typingEl = null; }
    },

    _showSessionEnded() {
        const wrapper = this._createElement('div', 'inmed-cb-session-end');
        const btn = this._createElement('button', 'inmed-cb-restart-btn');
        btn.textContent = 'Nueva conversación';
        btn.addEventListener('click', () => {
            this.messagesEl.innerHTML = '';
            this.token = null;
            this.sessionState = null;
            this.inputEl.disabled = false;
            this.inputEl.placeholder = 'Ingresa tu identificación...';
            this._initSession();
        });
        wrapper.appendChild(btn);
        this.messagesEl.appendChild(wrapper);
        this._scrollToBottom();
    },

    // =============================================
    // Voice Recording (Speech-to-Text)
    // =============================================

    async _toggleRecording() {
        if (this.isLoading) return;

        if (this.isRecording) {
            this._stopRecording();
        } else {
            await this._startRecording();
        }
    },

    async _startRecording() {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            this._addMessage('assistant', 'Tu navegador no soporta grabación de audio.');
            return;
        }

        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            this._audioChunks = [];
            this._mediaRecorder = new MediaRecorder(stream, { mimeType: this._getAudioMimeType() });

            this._mediaRecorder.ondataavailable = (e) => {
                if (e.data.size > 0) this._audioChunks.push(e.data);
            };

            this._mediaRecorder.onstop = () => {
                stream.getTracks().forEach(t => t.stop());
                this._processAudioRecording();
            };

            this._mediaRecorder.start();
            this.isRecording = true;
            this.micBtn.classList.add('inmed-cb-mic-recording');
            this.micBtn.querySelector('.inmed-cb-mic-icon').style.display = 'none';
            this.micBtn.querySelector('.inmed-cb-stop-icon').style.display = '';
            this.micBtn.title = 'Detener grabación';
            this.inputEl.placeholder = 'Grabando...';
            this.inputEl.disabled = true;
        } catch (err) {
            if (err.name === 'NotAllowedError') {
                this._addMessage('assistant', 'Debes permitir el acceso al micrófono para usar esta función.');
            } else {
                this._addMessage('assistant', 'No se pudo acceder al micrófono.');
            }
        }
    },

    _stopRecording() {
        if (this._mediaRecorder && this._mediaRecorder.state === 'recording') {
            this._mediaRecorder.stop();
        }
        this.isRecording = false;
        this.micBtn.classList.remove('inmed-cb-mic-recording');
        this.micBtn.querySelector('.inmed-cb-mic-icon').style.display = '';
        this.micBtn.querySelector('.inmed-cb-stop-icon').style.display = 'none';
        this.micBtn.title = 'Grabar mensaje de voz';
        this.inputEl.disabled = false;
        this.inputEl.placeholder = this.sessionState === 'pending_id' ? 'Ingresa tu identificación...' : 'Escribe tu mensaje...';
    },

    async _processAudioRecording() {
        if (this._audioChunks.length === 0) return;

        const blob = new Blob(this._audioChunks, { type: this._getAudioMimeType() });
        this._audioChunks = [];

        // Convertir a base64
        const base64 = await this._blobToBase64(blob);

        this.isLoading = true;
        this.sendBtn.disabled = true;
        this.micBtn.disabled = true;
        this._showTyping();

        try {
            const result = await rpc('/chatbot/transcribe', {
                token: this.token,
                audio_base64: base64,
            });

            this._hideTyping();
            this.isLoading = false;
            this.micBtn.disabled = false;

            if (result.success && result.text) {
                // Inyectar texto transcrito en el input y enviar automáticamente
                this.inputEl.value = result.text;
                this._onInputChange();
                this._handleSend();
            } else {
                this._addMessage('assistant', result.error || 'No se pudo transcribir el audio.');
                this._onInputChange();
            }
        } catch (err) {
            this._hideTyping();
            this.isLoading = false;
            this.micBtn.disabled = false;
            this._addMessage('assistant', 'Error al transcribir el audio. Intenta de nuevo.');
            this._onInputChange();
        }
    },

    _blobToBase64(blob) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onloadend = () => {
                // Quitar prefijo "data:audio/...;base64,"
                const base64 = reader.result.split(',')[1];
                resolve(base64);
            };
            reader.onerror = reject;
            reader.readAsDataURL(blob);
        });
    },

    _getAudioMimeType() {
        if (MediaRecorder.isTypeSupported('audio/webm;codecs=opus')) return 'audio/webm;codecs=opus';
        if (MediaRecorder.isTypeSupported('audio/webm')) return 'audio/webm';
        if (MediaRecorder.isTypeSupported('audio/mp4')) return 'audio/mp4';
        return '';
    },

    // =============================================
    // Register Form (inline en el chat)
    // =============================================

    _showRegisterConfirm(hasAccount, vat) {
        const wrapper = this._createElement('div', 'inmed-cb-confirm-buttons');
        wrapper.style.margin = '8px 4px';

        const btnYes = this._createElement('button', 'inmed-cb-confirm-btn inmed-cb-confirm-yes');
        btnYes.textContent = 'Sí, registrarme';
        btnYes.addEventListener('click', () => {
            wrapper.remove();
            this._addMessage('user', 'Sí, quiero registrarme');
            this._showRegisterForm(hasAccount, vat);
        });

        const btnNo = this._createElement('button', 'inmed-cb-confirm-btn inmed-cb-confirm-no');
        btnNo.textContent = 'No, gracias';
        btnNo.addEventListener('click', () => {
            wrapper.remove();
            this._addMessage('user', 'No, gracias');
            this.sessionState = 'pending_id';
            this._addMessage('assistant', 'No hay problema. Puedes intentar con otro número de identificación.');
            this.inputEl.placeholder = 'Ingresa tu identificación...';
        });

        wrapper.appendChild(btnYes);
        wrapper.appendChild(btnNo);
        this.messagesEl.appendChild(wrapper);
        this._scrollToBottom();
    },

    _showRegisterForm(hasAccount, vat) {
        const card = this._createElement('div', 'inmed-cb-register-card');
        let extraFields = '';

        if (hasAccount) {
            extraFields = `
                <div class="inmed-cb-reg-field">
                    <label>Email</label>
                    <input type="email" class="inmed-cb-reg-input" data-field="email" placeholder="correo@ejemplo.com"/>
                </div>
                <div class="inmed-cb-reg-field">
                    <label>Dirección</label>
                    <input type="text" class="inmed-cb-reg-input" data-field="street" placeholder="Calle principal, número"/>
                </div>
                <div class="inmed-cb-reg-field">
                    <label>Ciudad</label>
                    <input type="text" class="inmed-cb-reg-input" data-field="city" placeholder="Ciudad"/>
                </div>
            `;
        }

        card.innerHTML = `
            <div class="inmed-cb-reg-title">Registro de Cliente</div>
            <div class="inmed-cb-reg-vat">Identificación: <strong>${this._escapeHtml(vat)}</strong></div>
            <div class="inmed-cb-reg-field">
                <label>Nombre completo <span style="color:#ef4444">*</span></label>
                <input type="text" class="inmed-cb-reg-input" data-field="name" placeholder="Nombres y apellidos" required/>
            </div>
            <div class="inmed-cb-reg-field">
                <label>Teléfono / Celular <span style="color:#ef4444">*</span></label>
                <input type="tel" class="inmed-cb-reg-input" data-field="phone" placeholder="09XXXXXXXX" required/>
            </div>
            ${hasAccount ? '' : `
            <div class="inmed-cb-reg-field">
                <label>Email</label>
                <input type="email" class="inmed-cb-reg-input" data-field="email" placeholder="correo@ejemplo.com"/>
            </div>
            `}
            ${extraFields}
            <div class="inmed-cb-reg-error" style="display:none"></div>
            <div class="inmed-cb-confirm-buttons">
                <button class="inmed-cb-confirm-btn inmed-cb-confirm-yes inmed-cb-reg-submit">Registrarme</button>
                <button class="inmed-cb-confirm-btn inmed-cb-confirm-no inmed-cb-reg-cancel">Cancelar</button>
            </div>
        `;

        const submitBtn = card.querySelector('.inmed-cb-reg-submit');
        const cancelBtn = card.querySelector('.inmed-cb-reg-cancel');

        submitBtn.addEventListener('click', () => this._submitRegister(card));
        cancelBtn.addEventListener('click', () => {
            card.remove();
            this.sessionState = 'pending_id';
            this._addMessage('assistant', 'No hay problema. Puedes intentar con otro número de identificación.');
            this.inputEl.placeholder = 'Ingresa tu identificación...';
        });

        this.messagesEl.appendChild(card);
        this._scrollToBottom();

        // Deshabilitar input principal mientras se muestra el formulario
        this.inputEl.disabled = true;
    },

    async _submitRegister(card) {
        const fields = {};
        card.querySelectorAll('.inmed-cb-reg-input').forEach(input => {
            fields[input.dataset.field] = input.value.trim();
        });

        const errorEl = card.querySelector('.inmed-cb-reg-error');

        if (!fields.name || fields.name.length < 3) {
            errorEl.textContent = 'El nombre es obligatorio (mínimo 3 caracteres).';
            errorEl.style.display = 'block';
            return;
        }
        if (!fields.phone || fields.phone.length < 7) {
            errorEl.textContent = 'El teléfono es obligatorio.';
            errorEl.style.display = 'block';
            return;
        }

        errorEl.style.display = 'none';

        // Deshabilitar botones
        card.querySelectorAll('button').forEach(b => b.disabled = true);
        card.querySelector('.inmed-cb-reg-submit').textContent = 'Registrando...';

        try {
            const result = await rpc('/chatbot/register', {
                token: this.token,
                name: fields.name,
                phone: fields.phone,
                email: fields.email || '',
                street: fields.street || '',
                city: fields.city || '',
            });

            card.remove();
            this.inputEl.disabled = false;

            if (result.success) {
                this.sessionState = 'active';
                // Tarjeta de registro exitoso
                this._renderRegisterSuccess(result.patient_name);
                this._addMessage('assistant', result.message);
                if (result.especialidades && result.especialidades.length > 0) {
                    this._renderOptionButtons(result.especialidades, 'especialidad');
                }
                this.inputEl.placeholder = 'Escribe tu mensaje...';
            } else {
                errorEl.textContent = result.error || 'Error al registrar.';
                errorEl.style.display = 'block';
                card.querySelectorAll('button').forEach(b => b.disabled = false);
                card.querySelector('.inmed-cb-reg-submit').textContent = 'Registrarme';
            }
        } catch (err) {
            card.remove();
            this.inputEl.disabled = false;
            this._addMessage('assistant', 'Error de conexión. Intenta de nuevo.');
        }
    },

    _renderRegisterSuccess(name) {
        const card = this._createElement('div', 'inmed-cb-register-success');
        card.innerHTML = `
            <div class="inmed-cb-regsuc-icon">
                <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
                    <polyline points="22 4 12 14.01 9 11.01"/>
                </svg>
            </div>
            <div class="inmed-cb-regsuc-title">Registro Exitoso</div>
            <div class="inmed-cb-regsuc-name">${this._escapeHtml(name)}</div>
            <div class="inmed-cb-regsuc-text">Cliente registrado correctamente</div>
        `;
        this.messagesEl.appendChild(card);
        this._scrollToBottom();
    },

    // =============================================
    // Helpers
    // =============================================

    _formatText(text) {
        if (!text) return '';
        let html = this._escapeHtml(text);
        html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        html = html.replace(/\n/g, '<br>');
        return html;
    },

    _escapeHtml(text) {
        if (!text) return '';
        return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    },

    _createElement(tag, classes, innerHTML) {
        const el = document.createElement(tag);
        if (classes) el.className = classes;
        if (innerHTML) el.innerHTML = innerHTML;
        return el;
    },

    _scrollToBottom() {
        requestAnimationFrame(() => { this.messagesEl.scrollTop = this.messagesEl.scrollHeight; });
    },

    _onInputChange() {
        this.inputEl.style.height = 'auto';
        this.inputEl.style.height = Math.min(this.inputEl.scrollHeight, 100) + 'px';
        this.sendBtn.disabled = !this.inputEl.value.trim() || this.isLoading;
    },
});
