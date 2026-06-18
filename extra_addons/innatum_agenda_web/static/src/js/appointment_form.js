/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";

publicWidget.registry.AppointmentFormPublic = publicWidget.Widget.extend({
    selector: '.inmed-appointment-page',

    events: {
        'change #servicio_id': '_onServicioChange',
        'change #professional_id': '_onProfessionalChange',
        'change #fecha': '_onFechaChange',
        'change #horario': '_onHorarioChange',
        'blur #vat': '_onVatBlur',
        'change #country_id': '_onCountryChange',
        'submit #appointment_form': '_onFormSubmit',
    },

    start: function () {
        this._super.apply(this, arguments);

        this.servicioField = this.el.querySelector('#servicio_id');
        this.professionalField = this.el.querySelector('#professional_id');
        this.fechaField = this.el.querySelector('#fecha');
        this.horarioField = this.el.querySelector('#horario');
        this.turnoIdField = this.el.querySelector('#turno_id');
        this.vatField = this.el.querySelector('#vat');
        this.nameField = this.el.querySelector('#name');
        this.phoneField = this.el.querySelector('#phone');
        this.emailField = this.el.querySelector('#email');
        this.submitButton = this.el.querySelector('#submit_btn');
        this.summaryBox = this.el.querySelector('#selection_summary');
        this.summaryText = this.el.querySelector('#summary_text');
        this.vatMessage = this.el.querySelector('#vat_message');
        this.newPatientFields = this.el.querySelector('#new_patient_fields');
        this.birthdateField = this.el.querySelector('#birthdate');
        this.genderField = this.el.querySelector('#gender');
        this.countryField = this.el.querySelector('#country_id');
        this.stateField = this.el.querySelector('#state_id');
        this.cityField = this.el.querySelector('#city');
        this.streetField = this.el.querySelector('#street');

        this.turnoSelected = false;
        this.vatVerified = false;
        this.isNewPatient = false;

        // Pre-seleccionar desde URL (?servicio_id=X&professional_id=Y)
        this._applyUrlParams();

        return Promise.resolve();
    },

    // ========================
    // Cascada de selección
    // ========================

    _onServicioChange: async function () {
        var servicioId = this.servicioField.value;

        this._resetField(this.professionalField, 'Cargando profesionales...');
        this._resetField(this.fechaField, 'Primero seleccione profesional');
        this._resetField(this.horarioField, 'Primero seleccione fecha');
        this._hideSummary();
        this.turnoSelected = false;
        this._updateButtonState();

        if (!servicioId) {
            this._resetField(this.professionalField, 'Primero seleccione especialidad');
            this.professionalField.disabled = true;
            return;
        }

        try {
            var result = await rpc('/citas/get_professionals', {
                servicio_id: servicioId,
            });

            if (result.success && result.professionals.length > 0) {
                this._populateSelect(
                    this.professionalField, result.professionals, 'Seleccione un profesional...'
                );
                this.professionalField.disabled = false;

                // Auto-seleccionar profesional pendiente desde URL
                if (this._pendingProfessionalId) {
                    this.professionalField.value = this._pendingProfessionalId;
                    this._pendingProfessionalId = null;
                    if (this.professionalField.value) {
                        await this._onProfessionalChange();
                    }
                }
            } else {
                this._resetField(
                    this.professionalField, 'No hay profesionales disponibles'
                );
            }
        } catch (error) {
            console.error('Error al cargar profesionales:', error);
            this._resetField(this.professionalField, 'Error al cargar profesionales');
        }
    },

    _onProfessionalChange: async function () {
        var servicioId = this.servicioField.value;
        var professionalId = this.professionalField.value;

        this._resetField(this.fechaField, 'Cargando fechas...');
        this._resetField(this.horarioField, 'Primero seleccione fecha');
        this._hideSummary();
        this.turnoSelected = false;
        this._updateButtonState();

        if (!professionalId) {
            this._resetField(this.fechaField, 'Primero seleccione profesional');
            this.fechaField.disabled = true;
            return;
        }

        try {
            var result = await rpc('/citas/get_available_dates', {
                servicio_id: servicioId,
                professional_id: professionalId,
            });

            if (result.success && result.dates.length > 0) {
                var options = result.dates.map(function (d) {
                    var parts = d.split('-');
                    var label = parts[2] + '/' + parts[1] + '/' + parts[0];
                    return { id: d, name: label };
                });
                this._populateSelect(
                    this.fechaField, options, 'Seleccione una fecha...'
                );
                this.fechaField.disabled = false;
            } else {
                this._resetField(
                    this.fechaField, 'No hay fechas disponibles'
                );
            }
        } catch (error) {
            console.error('Error al cargar fechas:', error);
            this._resetField(this.fechaField, 'Error al cargar fechas');
        }
    },

    _onFechaChange: async function () {
        var servicioId = this.servicioField.value;
        var professionalId = this.professionalField.value;
        var fecha = this.fechaField.value;

        this._resetField(this.horarioField, 'Cargando horarios...');
        this._hideSummary();
        this.turnoSelected = false;
        this._updateButtonState();

        if (!fecha) {
            this._resetField(this.horarioField, 'Primero seleccione fecha');
            this.horarioField.disabled = true;
            return;
        }

        try {
            var result = await rpc('/citas/get_available_slots', {
                servicio_id: servicioId,
                professional_id: professionalId,
                date: fecha,
            });

            if (result.success && result.slots.length > 0) {
                var options = result.slots.map(function (s) {
                    return {
                        id: s.id,
                        name: s.hora + ' (' + s.duracion + ' min)',
                    };
                });
                this._populateSelect(
                    this.horarioField, options, 'Seleccione un horario...'
                );
                this.horarioField.disabled = false;
            } else {
                this._resetField(
                    this.horarioField, 'No hay horarios disponibles'
                );
            }
        } catch (error) {
            console.error('Error al cargar horarios:', error);
            this._resetField(this.horarioField, 'Error al cargar horarios');
        }
    },

    _onHorarioChange: function () {
        var turnoId = this.horarioField.value;

        if (turnoId) {
            this.turnoIdField.value = turnoId;
            this.turnoSelected = true;

            var servicio = this.servicioField.options[this.servicioField.selectedIndex].text;
            var professional = this.professionalField.options[this.professionalField.selectedIndex].text;
            var fecha = this.fechaField.options[this.fechaField.selectedIndex].text;
            var hora = this.horarioField.options[this.horarioField.selectedIndex].text;

            this.summaryText.textContent =
                servicio + ' — ' + professional + ' — ' + fecha + ' a las ' + hora;
            this.summaryBox.style.display = 'block';
        } else {
            this.turnoIdField.value = '';
            this.turnoSelected = false;
            this._hideSummary();
        }

        this._updateButtonState();
    },

    // ========================
    // Cascada país → provincia
    // ========================

    _onCountryChange: async function () {
        var countryId = this.countryField.value;
        this._resetField(this.stateField, 'Cargando provincias...');

        if (!countryId) {
            this._resetField(this.stateField, 'Primero seleccione país');
            return;
        }

        try {
            var result = await rpc('/citas/get_states', {
                country_id: countryId,
            });
            if (result.success && result.states.length > 0) {
                this._populateSelect(
                    this.stateField, result.states, 'Seleccione una provincia...'
                );
                this.stateField.disabled = false;
            } else {
                this._resetField(this.stateField, 'No hay provincias disponibles');
            }
        } catch (error) {
            console.error('Error al cargar provincias:', error);
            this._resetField(this.stateField, 'Error al cargar provincias');
        }
    },

    _loadStatesForDefaultCountry: function () {
        if (this.countryField && this.countryField.value) {
            this._onCountryChange();
        }
    },

    // ========================
    // Verificación de cédula
    // ========================

    _onVatBlur: async function () {
        var vat = this.vatField.value.trim();
        this.vatVerified = false;
        this._clearVatMessage();

        if (!vat) {
            this._updateButtonState();
            return;
        }

        try {
            var result = await rpc('/citas/verificar_cliente', { vat: vat });

            if (result.success && result.exists) {
                this.nameField.value = result.name;
                this.phoneField.value = result.phone;
                this.emailField.value = result.email;
                this.nameField.readOnly = true;
                this.isNewPatient = false;
                this.newPatientFields.style.display = 'none';
                this._showVatMessage(
                    'success', 'Paciente encontrado: ' + result.name
                );
            } else {
                this.nameField.readOnly = false;
                this.isNewPatient = true;
                this.newPatientFields.style.display = '';
                this._loadStatesForDefaultCountry();
                if (result.success) {
                    this._showVatMessage(
                        'info', 'Paciente nuevo. Complete sus datos a continuación.'
                    );
                }
            }
            this.vatVerified = true;
        } catch (error) {
            console.error('Error al verificar cédula:', error);
            this._showVatMessage('error', 'Error al verificar el documento.');
        }

        this._updateButtonState();
    },

    // ========================
    // Validación del formulario
    // ========================

    _onFormSubmit: function (ev) {
        if (!this.turnoSelected) {
            ev.preventDefault();
            this._showFormMessage('error', 'Debe seleccionar un horario.');
            return false;
        }

        if (!this.vatField.value.trim()) {
            ev.preventDefault();
            this._showFormMessage('error', 'Debe ingresar su cédula.');
            this.vatField.focus();
            return false;
        }

        if (!this.nameField.value.trim()) {
            ev.preventDefault();
            this._showFormMessage('error', 'Debe ingresar su nombre completo.');
            this.nameField.focus();
            return false;
        }

        if (!this.phoneField.value.trim()) {
            ev.preventDefault();
            this._showFormMessage('error', 'Debe ingresar su número de celular.');
            this.phoneField.focus();
            return false;
        }

        if (this.isNewPatient) {
            if (!this.birthdateField.value) {
                ev.preventDefault();
                this._showFormMessage('error', 'Debe ingresar su fecha de nacimiento.');
                this.birthdateField.focus();
                return false;
            }
            if (!this.genderField.value) {
                ev.preventDefault();
                this._showFormMessage('error', 'Debe seleccionar su género.');
                this.genderField.focus();
                return false;
            }
            if (!this.countryField.value) {
                ev.preventDefault();
                this._showFormMessage('error', 'Debe seleccionar su país.');
                this.countryField.focus();
                return false;
            }
            if (!this.stateField.value) {
                ev.preventDefault();
                this._showFormMessage('error', 'Debe seleccionar su provincia.');
                this.stateField.focus();
                return false;
            }
            if (!this.cityField.value.trim()) {
                ev.preventDefault();
                this._showFormMessage('error', 'Debe ingresar su ciudad.');
                this.cityField.focus();
                return false;
            }
            if (!this.streetField.value.trim()) {
                ev.preventDefault();
                this._showFormMessage('error', 'Debe ingresar su dirección.');
                this.streetField.focus();
                return false;
            }
        }

        this.submitButton.disabled = true;
        this.submitButton.innerHTML =
            '<i class="fa fa-spinner fa-spin me-2"></i> Procesando...';
        return true;
    },

    // ========================
    // Pre-selección desde URL
    // ========================

    _applyUrlParams: async function () {
        var params = new URLSearchParams(window.location.search);
        var servicioId = params.get('servicio_id');
        var professionalId = params.get('professional_id');

        if (!servicioId && !professionalId) {
            return;
        }

        // Si tenemos servicio_id, seleccionarlo y disparar cascada
        if (servicioId && this.servicioField) {
            this.servicioField.value = servicioId;
            await this._onServicioChange();

            // Si tenemos professional_id, esperar a que carguen los profesionales y seleccionar
            if (professionalId && this.professionalField) {
                this.professionalField.value = professionalId;
                await this._onProfessionalChange();
            }
        } else if (professionalId && !servicioId) {
            // Solo profesional sin servicio: buscar en qué servicios aparece
            // El usuario tendrá que elegir la especialidad primero
            // Marcamos el profesional para seleccionarlo cuando cargue la lista
            this._pendingProfessionalId = professionalId;
        }
    },

    // ========================
    // Helpers
    // ========================

    _populateSelect: function (selectEl, items, placeholder) {
        selectEl.innerHTML = '';
        var defaultOpt = document.createElement('option');
        defaultOpt.value = '';
        defaultOpt.textContent = placeholder;
        selectEl.appendChild(defaultOpt);

        items.forEach(function (item) {
            var opt = document.createElement('option');
            opt.value = item.id;
            opt.textContent = item.name;
            selectEl.appendChild(opt);
        });
    },

    _resetField: function (selectEl, placeholder) {
        selectEl.innerHTML = '';
        var opt = document.createElement('option');
        opt.value = '';
        opt.textContent = placeholder;
        selectEl.appendChild(opt);
        selectEl.disabled = true;
    },

    _hideSummary: function () {
        if (this.summaryBox) {
            this.summaryBox.style.display = 'none';
        }
    },

    _updateButtonState: function () {
        if (!this.submitButton) {
            return;
        }
        var ready = this.turnoSelected && this.vatField.value.trim();
        this.submitButton.disabled = !ready;
    },

    _showVatMessage: function (type, message) {
        if (!this.vatMessage) {
            return;
        }
        this.vatMessage.textContent = message;
        this.vatMessage.className = 'inmed-field-message inmed-msg-' + type;
    },

    _clearVatMessage: function () {
        if (this.vatMessage) {
            this.vatMessage.textContent = '';
            this.vatMessage.className = 'inmed-field-message';
        }
    },

    _showFormMessage: function (type, message) {
        var el = this.el.querySelector('#form_messages');
        if (el) {
            el.textContent = message;
            el.className = 'inmed-field-message inmed-msg-' + type;
        }
    },
});
