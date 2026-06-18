# -*- coding: utf-8 -*-

import logging
from datetime import datetime, timedelta

from odoo import http, fields
from odoo.exceptions import ValidationError
from odoo.http import request

_logger = logging.getLogger(__name__)


class AppointmentController(http.Controller):

    def _tenant_company(self):
        """Devuelve la company del tenant según el website actual.
        Es la 'clave maestra' que aísla todos los queries en endpoints
        públicos para que un visitante de cliente1.innatum.com no vea
        datos de cliente2.innatum.com."""
        return request.website.company_id

    def _tenant_tz(self):
        """TZ para mostrar/generar slots en el sitio público.

        En Odoo el TZ vive en res.users (no en res.company). Para visitantes
        anónimos `request.env.user` es el Public User, que típicamente no
        tiene TZ seteado. Caemos al admin del sistema, que al crear la BD
        recibe automáticamente un TZ válido. Esto encaja con el modelo
        '1 BD = 1 país': todos los tenants de la BD comparten ese TZ.
        """
        if request.env.user.tz:
            return request.env.user.tz
        # sudo: el Public User del tenant (uno por website en multi-company)
        # no tiene permiso de leer res.users del admin del sistema.
        admin = request.env.ref('base.user_admin', raise_if_not_found=False)
        return (admin and admin.sudo().tz) or 'UTC'

    def _es_profesional_publico(self, employee):
        """Devuelve True si el empleado debe aparecer en el sitio web público.
        Excluye solo a usuarios SaaS-level (Innatum / system admin); cualquier
        empleado del tenant aparece si tiene planificación aprobada, incluso
        si es Admin u Operador (caso típico: dueño que también atiende)."""
        if not employee.user_id:
            return True
        return not employee.user_id.has_group('base.group_system')

    @http.route(['/', '/inicio'], type='http', auth='public', website=True, sitemap=True)
    def homepage(self, **kwargs):
        """Página principal del negocio.
        Muestra solo empleados que tienen al menos una planificación aprobada
        Y turnos disponibles, junto con los servicios que brindan."""
        company = self._tenant_company()
        Employee = request.env['hr.employee'].sudo()
        profesionales = Employee.search([
            ('active', '=', True),
            ('company_id', '=', company.id),
        ], order='name')
        # Excluir Operadores y Administradores (no brindan servicios)
        profesionales = profesionales.filtered(self._es_profesional_publico)

        Config = request.env['innatum.agenda.config'].sudo()
        Turno = request.env['innatum.agenda.turno'].sudo()
        prof_con_turnos = []
        prof_servicios = {}  # {prof_id: [{'name', 'code'}, ...]}
        for prof in profesionales:
            # Debe tener al menos una planificación aprobada
            configs = Config.search([
                ('professional_id', '=', prof.id),
                ('state', '=', 'approved'),
                ('company_id', '=', company.id),
            ])
            if not configs:
                continue
            # Y al menos un turno disponible a futuro
            tiene = Turno.search([
                ('professional_id', '=', prof.id),
                ('state', '=', 'available'),
                ('date_start', '>=', fields.Datetime.now()),
                ('company_id', '=', company.id),
            ], limit=1)
            if not tiene:
                continue
            prof_con_turnos.append(prof)
            # Servicios derivados de sus planificaciones aprobadas
            servicios_prof = configs.mapped('servicio_ids')
            prof_servicios[prof.id] = [
                {'name': s.name, 'code': s.code} for s in servicios_prof
            ]

        # Servicios con disponibilidad para la sección de servicios
        Servicio = request.env['innatum.agenda.servicio'].sudo()
        servicios = Servicio.search([('company_ids', 'in', [company.id])])
        servicios_disponibles = servicios.filtered(
            lambda s: Turno.search([
                ('servicio_ids', 'in', s.id),
                ('state', '=', 'available'),
                ('date_start', '>=', fields.Datetime.now()),
                ('company_id', '=', company.id),
            ], limit=1)
        )

        # Detectar profesionales con foto real
        prof_con_foto = set()
        for prof in prof_con_turnos:
            if prof.image_1920 and len(prof.image_1920) > 1000:
                prof_con_foto.add(prof.id)

        template = self._homepage_template(company)
        return request.render(template, {
            'company': company,
            'profesionales': prof_con_turnos,
            'servicios': servicios_disponibles,
            'prof_con_foto': prof_con_foto,
            'prof_servicios': prof_servicios,
        })

    def _homepage_template(self, company):
        """Devuelve el id del template a renderizar según el vertical del tenant.

        Cada vertical instalable aporta su template estilizado.
        Si el módulo correspondiente NO está instalado, caemos al
        homepage genérico para que el sitio nunca quede roto.
        """
        vertical_templates = {
            'odonto': 'innatum_agenda_web_odonto.homepage',
        }
        vertical = getattr(company, 'vertical', 'generic') or 'generic'
        template = vertical_templates.get(vertical)
        if template:
            view = request.env['ir.ui.view'].sudo().search(
                [('key', '=', template)], limit=1,
            )
            if view:
                return template
        return 'innatum_agenda_web.homepage'

    @http.route('/citas', type='http', auth='public', website=True)
    def appointment_form(self, **kwargs):
        """Muestra el formulario público de agendamiento."""
        company = self._tenant_company()
        servicios = request.env['innatum.agenda.servicio'].sudo().search([
            ('company_ids', 'in', [company.id]),
        ])
        countries = request.env['res.country'].sudo().search([], order='name')
        default_country = company.country_id or request.env.ref(
            'base.ec', raise_if_not_found=False,
        )
        values = {
            'company': company,
            'vertical': getattr(company, 'vertical', 'generic') or 'generic',
            'servicios': servicios,
            'countries': countries,
            'default_country_id': default_country.id if default_country else False,
            'page_name': 'appointment_form',
        }
        return request.render('innatum_agenda_web.appointment_form_template', values)

    @http.route('/citas/get_professionals', type='json', auth='public', website=True)
    def get_professionals(self, servicio_id):
        """Retorna los profesionales con turnos disponibles para un servicio."""
        try:
            servicio_id = int(servicio_id)
            company = self._tenant_company()
            Turno = request.env['innatum.agenda.turno'].sudo()
            turnos = Turno.search([
                ('servicio_ids', 'in', servicio_id),
                ('state', '=', 'available'),
                ('publicar', '=', True),
                ('date_start', '>=', fields.Datetime.now()),
                ('company_id', '=', company.id),
            ])
            prof_ids = turnos.mapped('professional_id').filtered(
                self._es_profesional_publico
            )
            professionals = [{
                'id': p.id,
                'name': p.name,
            } for p in prof_ids]
            return {'success': True, 'professionals': professionals}
        except Exception as e:
            _logger.warning(f"Error al obtener profesionales: {e}")
            return {'success': False, 'message': 'Error al cargar profesionales.'}

    @http.route('/citas/get_available_dates', type='json', auth='public', website=True)
    def get_available_dates(self, servicio_id, professional_id):
        """Retorna las fechas que tienen turnos disponibles."""
        try:
            servicio_id = int(servicio_id)
            professional_id = int(professional_id)
            company = self._tenant_company()
            Turno = request.env['innatum.agenda.turno'].sudo()
            turnos = Turno.search([
                ('servicio_ids', 'in', servicio_id),
                ('professional_id', '=', professional_id),
                ('state', '=', 'available'),
                ('publicar', '=', True),
                ('date_start', '>=', fields.Datetime.now()),
                ('company_id', '=', company.id),
            ], order='date_start asc')
            tz = self._tenant_tz()
            fechas = set()
            for t in turnos:
                local_dt = fields.Datetime.context_timestamp(
                    request.env.user.with_context(tz=tz), t.date_start,
                )
                fechas.add(local_dt.strftime('%Y-%m-%d'))
            return {
                'success': True,
                'dates': sorted(list(fechas)),
            }
        except Exception as e:
            _logger.warning(f"Error al obtener fechas: {e}")
            return {'success': False, 'message': 'Error al cargar fechas.'}

    @http.route('/citas/get_available_slots', type='json', auth='public', website=True)
    def get_available_slots(self, servicio_id, professional_id, date):
        """Retorna los horarios disponibles para una fecha específica."""
        try:
            servicio_id = int(servicio_id)
            professional_id = int(professional_id)
            company = self._tenant_company()
            import pytz
            tz_name = self._tenant_tz()
            tz = pytz.timezone(tz_name)
            fecha_local = datetime.strptime(date, '%Y-%m-%d')
            inicio_dia = tz.localize(fecha_local.replace(
                hour=0, minute=0, second=0,
            )).astimezone(pytz.UTC).replace(tzinfo=None)
            fin_dia = tz.localize(fecha_local.replace(
                hour=23, minute=59, second=59,
            )).astimezone(pytz.UTC).replace(tzinfo=None)

            Turno = request.env['innatum.agenda.turno'].sudo()
            turnos = Turno.search([
                ('servicio_ids', 'in', servicio_id),
                ('professional_id', '=', professional_id),
                ('state', '=', 'available'),
                ('publicar', '=', True),
                ('date_start', '>=', inicio_dia),
                ('date_start', '<=', fin_dia),
                ('company_id', '=', company.id),
            ], order='date_start asc')

            slots = []
            for t in turnos:
                # context_timestamp espera el NOMBRE del TZ (string), no
                # el objeto pytz. Pasarle el objeto hace que ignore el TZ
                # y devuelva UTC.
                local_dt = fields.Datetime.context_timestamp(
                    request.env.user.with_context(tz=tz_name), t.date_start,
                )
                slots.append({
                    'id': t.id,
                    'hora': local_dt.strftime('%H:%M'),
                    'duracion': int(t.duration),
                })
            return {'success': True, 'slots': slots}
        except Exception as e:
            _logger.warning(f"Error al obtener horarios: {e}")
            return {'success': False, 'message': 'Error al cargar horarios.'}

    @http.route('/citas/get_states', type='json', auth='public', website=True)
    def get_states(self, country_id):
        """Retorna las provincias/estados de un país."""
        try:
            country_id = int(country_id)
            states = request.env['res.country.state'].sudo().search([
                ('country_id', '=', country_id),
            ], order='name')
            return {
                'success': True,
                'states': [{'id': s.id, 'name': s.name} for s in states],
            }
        except Exception as e:
            _logger.warning(f"Error al obtener provincias: {e}")
            return {'success': False, 'message': 'Error al cargar provincias.'}

    @http.route('/citas/verificar_cliente', type='json', auth='public', website=True)
    def verificar_cliente(self, vat):
        """Verifica si el cliente ya existe como contacto en este tenant.
        Si hay duplicados con el mismo VAT (no debería con el nuevo
        constraint, pero por defensividad), devuelve el más completo."""
        try:
            vat = vat.strip()
            partner = self._find_partner_by_vat(vat)
            if partner:
                return {
                    'success': True,
                    'exists': True,
                    'name': partner.name,
                    'phone': partner.mobile or partner.phone or '',
                    'email': partner.email or '',
                }
            return {'success': True, 'exists': False}
        except Exception as e:
            _logger.warning(f"Error al verificar cliente: {e}")
            return {'success': False, 'message': 'Error al verificar documento.'}

    def _find_partner_by_vat(self, vat):
        """Busca el partner del TENANT actual con VAT dado.
        Cada tenant tiene sus propios partners (aislamiento multi-tenant);
        un mismo VAT puede existir en distintos tenants como personas
        registradas independientemente."""
        if not vat:
            return request.env['res.partner'].sudo().browse()
        company = self._tenant_company()
        partners = request.env['res.partner'].sudo().search([
            ('vat', '=', vat),
            ('company_id', '=', company.id),
        ])
        if not partners:
            return partners
        # Ranking: + email, + mobile/phone, id más alto (más reciente).
        return partners.sorted(
            key=lambda p: (
                bool(p.email),
                bool(p.mobile or p.phone),
                p.id,
            ),
            reverse=True,
        )[0]

    @http.route('/citas/submit', type='http', auth='public', website=True,
                methods=['POST'], csrf=True)
    def submit_appointment(self, **post):
        """Procesa el formulario y reserva el turno."""
        try:
            company = self._tenant_company()
            turno_id = int(post.get('turno_id', 0))
            Turno = request.env['innatum.agenda.turno'].sudo()
            turno = Turno.browse(turno_id)
            # Validación crítica multi-tenant: el turno debe pertenecer al
            # mismo tenant del website desde donde vino la reserva.
            if (not turno.exists()
                    or turno.state != 'available'
                    or turno.company_id != company):
                return request.render('innatum_agenda_web.appointment_error_template', {
                    'error': 'El horario seleccionado ya no está disponible. '
                             'Por favor, seleccione otro.',
                })

            # Buscar o crear contacto dentro de este tenant
            vat = post.get('vat', '').strip()
            Partner = request.env['res.partner'].sudo()
            partner = self._find_partner_by_vat(vat)

            form_phone = post.get('phone', '').strip()
            form_email = post.get('email', '').strip()

            if not partner:
                vals = {
                    'name': post.get('name', '').strip(),
                    'vat': vat,
                    'mobile': form_phone,
                    'email': form_email,
                    'street': post.get('street', '').strip(),
                    'city': post.get('city', '').strip(),
                    'company_id': company.id,
                }
                country_id = post.get('country_id')
                if country_id:
                    vals['country_id'] = int(country_id)
                state_id = post.get('state_id')
                if state_id:
                    vals['state_id'] = int(state_id)
                street2 = post.get('street2', '').strip()
                if street2:
                    vals['street2'] = street2
                partner = Partner.create(vals)
            else:
                # Si el partner existe pero le faltan mobile/email, los
                # completamos con lo que el cliente acaba de tipear.
                update_vals = {}
                if form_phone and not (partner.mobile or partner.phone):
                    update_vals['mobile'] = form_phone
                if form_email and not partner.email:
                    update_vals['email'] = form_email
                if update_vals:
                    partner.write(update_vals)

            # Determinar el servicio elegido (puede venir explícito en el form,
            # o si el turno tiene una sola opción, usar esa).
            servicio_elegido_id = False
            servicio_form = post.get('servicio_id')
            if servicio_form:
                try:
                    servicio_form = int(servicio_form)
                except (ValueError, TypeError):
                    servicio_form = False
                if servicio_form and servicio_form in turno.servicio_ids.ids:
                    servicio_elegido_id = servicio_form
            if not servicio_elegido_id:
                if turno.servicio_id:
                    servicio_elegido_id = turno.servicio_id.id
                elif len(turno.servicio_ids) == 1:
                    servicio_elegido_id = turno.servicio_ids.id
                else:
                    return request.render(
                        'innatum_agenda_web.appointment_error_template', {
                            'error': 'Debes elegir un servicio para este horario.',
                        })

            # Reservar el turno con el servicio elegido
            turno.write({
                'partner_id': partner.id,
                'servicio_id': servicio_elegido_id,
                'notes': post.get('notes', ''),
            })
            turno.action_reserve()

            # Acumular servicio en el historial del partner (CRM / segmentación).
            # Idempotente: el M2M no duplica si ya estaba.
            if servicio_elegido_id not in partner.servicios_consumidos_ids.ids:
                partner.servicios_consumidos_ids = [(4, servicio_elegido_id)]

            return request.render('innatum_agenda_web.appointment_success_template', {
                'turno': turno,
                'cliente': partner,
            })

        except ValidationError as e:
            _logger.info('Validación al agendar cita: %s', e)
            mensaje = str(e.args[0]) if e.args else (
                'No fue posible registrar el contacto. Verifique sus datos.'
            )
            return request.render('innatum_agenda_web.appointment_error_template', {
                'error': mensaje,
            })
        except Exception as e:
            _logger.error(f"Error al agendar cita: {e}")
            return request.render('innatum_agenda_web.appointment_error_template', {
                'error': 'Ocurrió un error al procesar su solicitud. '
                         'Por favor, intente nuevamente.',
            })
