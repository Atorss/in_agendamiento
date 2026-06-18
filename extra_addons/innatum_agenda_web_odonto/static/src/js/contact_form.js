/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";

publicWidget.registry.OdontoContactForm = publicWidget.Widget.extend({
    selector: '.odonto-home',
    events: {
        'click #odonto_submit_btn': '_onSubmit',
    },

    _onSubmit: function (ev) {
        ev.preventDefault();
        var self = this;
        var $form = this.$('#odonto_contact_form');
        var $btn = this.$('#odonto_submit_btn');
        var $msg = this.$('#odonto_form_message');

        var nombre = $form.find('input[name="nombre"]').val().trim();
        var apellido = $form.find('input[name="apellido"]').val().trim();
        var email = $form.find('input[name="email"]').val().trim();
        var telefono = $form.find('input[name="telefono"]').val().trim();
        var interes = $form.find('select[name="interes"]').val();

        // Validacion
        if (!nombre || !apellido || !email || !telefono || !interes) {
            self._showMessage($msg, 'Por favor completa todos los campos.', 'error');
            return;
        }

        // Email basico
        if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
            self._showMessage($msg, 'Ingresa un email valido.', 'error');
            return;
        }

        $btn.prop('disabled', true).html('<i class="fa fa-spinner fa-spin me-2"/>Enviando...');

        this._rpc({
            route: '/contacto/enviar',
            params: {
                nombre: nombre,
                apellido: apellido,
                email: email,
                telefono: telefono,
                interes: interes,
            },
        }).then(function (result) {
            if (result.success) {
                self._showMessage($msg, result.message, 'success');
                // Limpiar formulario
                $form.find('input').val('');
                $form.find('select').val('');
            } else {
                self._showMessage($msg, result.message, 'error');
            }
        }).catch(function () {
            self._showMessage($msg, 'Error de conexion. Intenta nuevamente.', 'error');
        }).finally(function () {
            $btn.prop('disabled', false).html('Enviar');
        });
    },

    _showMessage: function ($el, message, type) {
        var bgColor = type === 'success' ? '#10b981' : '#ef4444';
        $el.html(message)
           .css({
               'display': 'block',
               'background-color': bgColor,
               'color': '#fff',
               'padding': '12px 20px',
               'border-radius': '8px',
               'text-align': 'center',
               'margin-top': '10px',
           });
        setTimeout(function () {
            $el.fadeOut();
        }, 5000);
    },
});
