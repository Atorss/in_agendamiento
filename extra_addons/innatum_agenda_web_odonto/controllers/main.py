# -*- coding: utf-8 -*-
"""Endpoint del formulario de contacto del vertical odonto.

La homepage (`/`) la sirve `innatum_agenda_web.AppointmentController.homepage`,
que despacha el template correcto según `company.vertical`. Aquí solo
exponemos el endpoint del formulario de pre-reserva propio de este
vertical, que genera un partner pendiente y notifica al admin del tenant.
"""

import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class OdontoWebController(http.Controller):

    @http.route('/contacto/enviar', type='json', auth='public', website=True)
    def contact_submit(self, **post):
        """Recibe datos del formulario de pre-reserva.

        Crea un res.partner del tenant (filtrado por website.company_id)
        y postea un mensaje en el chatter de la company para que el admin
        del tenant lo vea. No usa crm.lead (no exigimos el stack CRM al SaaS).
        """
        nombre = (post.get('nombre') or '').strip()
        apellido = (post.get('apellido') or '').strip()
        email = (post.get('email') or '').strip()
        telefono = (post.get('telefono') or '').strip()
        interes_raw = (post.get('interes') or '').strip()

        if not all([nombre, apellido, email, telefono, interes_raw]):
            return {
                'success': False,
                'message': 'Todos los campos son obligatorios.',
            }

        company = request.website.company_id
        if not company:
            return {
                'success': False,
                'message': 'Sitio no asociado a una empresa. Contacte al administrador.',
            }

        # interes viene como id de innatum.agenda.servicio (puede ser id
        # numérico si lo eligió del select, o texto libre si no).
        servicio = request.env['innatum.agenda.servicio'].sudo().browse()
        if interes_raw.isdigit():
            servicio = request.env['innatum.agenda.servicio'].sudo().browse(
                int(interes_raw)
            ).exists()
            # Garantía multi-tenant: el servicio elegido debe pertenecer
            # al catálogo de este tenant.
            if servicio and company.id not in servicio.company_ids.ids:
                servicio = request.env['innatum.agenda.servicio'].sudo().browse()
        interes_label = servicio.name if servicio else interes_raw

        # Crear partner pre-reserva del tenant
        partner = request.env['res.partner'].sudo().create({
            'name': f'{nombre} {apellido}',
            'email': email,
            'phone': telefono,
            'company_id': company.id,
            'comment': f'Pre-reserva web. Interés: {interes_label}',
        })

        # Notificar al admin del tenant via chatter de la company
        try:
            company.sudo().message_post(
                body=(
                    f'<p><strong>Nueva pre-reserva web</strong></p>'
                    f'<ul>'
                    f'<li>Cliente: {nombre} {apellido}</li>'
                    f'<li>Email: {email}</li>'
                    f'<li>Teléfono: {telefono}</li>'
                    f'<li>Interés: {interes_label}</li>'
                    f'</ul>'
                ),
                subject='Pre-reserva web (vertical odonto)',
            )
        except Exception:
            _logger.exception(
                'No se pudo notificar pre-reserva en company %s', company.id,
            )

        _logger.info(
            'Pre-reserva odonto recibida: company=%s partner=%s interes=%s',
            company.id, partner.id, interes_label,
        )

        return {
            'success': True,
            'message': 'Tu solicitud fue enviada. Te contactaremos para confirmar.',
        }
