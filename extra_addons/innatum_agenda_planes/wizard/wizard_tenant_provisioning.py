# -*- coding: utf-8 -*-
"""Wizard de provisioning de tenants.

Único punto de entrada para crear un tenant SaaS. Garantiza que TODOS los
artefactos nazcan correctamente alineados con la arquitectura
multi-tenant: company, website (con subdominio), admin user del tenant
y suscripción inicial. Setea explícitamente company_id en los partners
estructurales para evitar la fuga "Peluquería ve Veterinaria PetCare".
"""

import logging
import re

from dateutil.relativedelta import relativedelta

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)

SUBDOMAIN_RE = re.compile(r'^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$')


class InAgendaTenantWizard(models.TransientModel):
    """Wizard que crea un tenant atómicamente."""
    _name = 'in_agenda.tenant.wizard'
    _description = 'Wizard: Crear Tenant'

    # --- Datos del tenant ---
    name = fields.Char(
        string='Nombre del tenant', required=True,
        help='Razón social o nombre comercial. Ej: "Peluquería Estilo".',
    )
    subdomain = fields.Char(
        string='Subdominio', required=True,
        help='Subdominio del tenant. Ej: "estilo" → estilo.innatum.com. '
             'Solo letras minúsculas, números y guiones. Debe ser único.',
    )
    base_domain = fields.Char(
        string='Dominio base', required=True,
        default='innatum.com',
        help='Dominio raíz donde viven los subdominios. En testing puede '
             'ser "localhost:8018".',
    )
    domain_scheme = fields.Selection(
        [('http', 'http://'), ('https', 'https://')],
        string='Protocolo', required=True, default='https',
    )

    # --- Admin del tenant ---
    admin_email = fields.Char(string='Email del admin', required=True)
    admin_name = fields.Char(string='Nombre del admin')
    admin_password = fields.Char(
        string='Password inicial', required=True,
        help='Mínimo 8 caracteres. El admin debería cambiarlo al primer login.',
    )
    crear_empleado_admin = fields.Boolean(
        string='El admin atiende como profesional',
        default=True,
        help='Si está tildado, se crea automáticamente un hr.employee '
             'asociado al admin del tenant. Es el caso normal: el dueño/a '
             'también atiende clientes. Destildá solo si el admin SOLO va '
             'a gestionar (no atender) y contratará colaboradores aparte.',
    )
    # Datos del admin como profesional (solo aplican si
    # crear_empleado_admin=True). Mismos campos que el wizard de colaborador
    # para mantener integridad entre ambos flujos.
    admin_identification_id = fields.Char(
        string='Cédula / Identificación del admin',
    )
    admin_work_phone = fields.Char(
        string='Teléfono del admin',
    )
    admin_job_title = fields.Char(
        string='Cargo / Puesto del admin',
        help='Ej: "Dueña", "Estilista principal", "Veterinario". '
             'Se muestra en el directorio público del sitio web.',
    )

    # --- Suscripción ---
    plan_id = fields.Many2one(
        'in_agenda.plan', string='Plan', required=True,
        domain=[('active', '=', True)],
    )
    fecha_inicio = fields.Date(
        string='Inicio', required=True, default=fields.Date.today,
    )
    ciclo_facturacion = fields.Selection([
        ('mensual', 'Mensual'),
        ('anual', 'Anual'),
    ], string='Ciclo de facturación', default='mensual', required=True,
        help='Mensual o anual. El anual aplica el descuento del plan y fija '
             'la duración en 12 meses.')
    duracion = fields.Integer(
        string='Duración', required=True, default=1,
        help='Cantidad de períodos según el ciclo: MESES si es mensual, '
             'AÑOS si es anual. Ej: ciclo anual + 1 = un año.')
    duracion_meses_total = fields.Integer(
        string='Duración total (meses)', compute='_compute_duracion_meses_total',
        help='Meses reales = duración × (12 si anual, 1 si mensual). Define '
             'la fecha de fin.')
    state_inicial = fields.Selection([
        ('trial', 'Trial'),
        ('active', 'Activa'),
    ], string='Estado inicial', default='active', required=True)

    # --- Funcionalidad gratuita: solo un check ---
    facturacion_sri_habilitada = fields.Boolean(
        string='Facturación electrónica (SRI)', default=False,
        help='Funcionalidad gratuita: habilita la emisión de comprobantes al '
             'SRI para este tenant.')

    # --- Add-ons de cobro a activar al crear (precio se congela del catálogo) ---
    addon_ids = fields.Many2many(
        'in_agenda.addon', string='Add-ons a activar',
        domain=[('active', '=', True)],
        help='Add-ons de pago que se activan desde el inicio de la '
             'suscripción. Más tarde puedes activar otros por fechas.')

    @api.depends('duracion', 'ciclo_facturacion')
    def _compute_duracion_meses_total(self):
        for rec in self:
            factor = 12 if rec.ciclo_facturacion == 'anual' else 1
            rec.duracion_meses_total = max(1, rec.duracion) * factor

    @api.onchange('ciclo_facturacion')
    def _onchange_ciclo_facturacion(self):
        # Al cambiar el ciclo, la duración vuelve a 1 período (1 mes o 1 año),
        # porque la unidad cambió.
        self.duracion = 1

    # --- Localización ---
    country_id = fields.Many2one(
        'res.country', string='País',
        default=lambda self: self.env.ref('base.ec', raise_if_not_found=False),
    )
    currency_id = fields.Many2one(
        'res.currency', string='Moneda',
        default=lambda self: self._default_currency(),
    )
    timezone = fields.Selection(
        lambda self: self._tz_get(),
        string='Zona horaria', default='America/Guayaquil', required=True,
    )

    vertical = fields.Selection(
        selection=lambda self: self.env['res.company']._fields['vertical'].selection,
        string='Vertical', default='generic', required=True,
        help='Define el look del sitio público del tenant. '
             'Si elegís "odontológico" debe estar instalado '
             '`innatum_agenda_web_odonto`.',
    )
    agenda_modo = fields.Selection(
        selection=lambda self: self.env['res.company']._fields['agenda_modo'].selection,
        string='Modo de agenda', default='planificada', required=True,
        help='Planificada: se pre-generan turnos de duración fija desde '
             'planificaciones (peluquería, lavadero). Directa: la '
             'disponibilidad se calcula on-demand desde el horario del '
             'profesional y el turno se crea al agendar con la duración del '
             'servicio (consultorios médicos/odontológicos). Se puede cambiar '
             'después; las citas agendadas se conservan.',
    )

    @api.model
    def _default_currency(self):
        usd = self.env.ref('base.USD', raise_if_not_found=False)
        return usd.id if usd else False

    @api.model
    def _tz_get(self):
        return self.env['res.partner']._fields['tz']._description_selection(self.env)

    # ------------------------------------------------------------------
    # Validaciones
    # ------------------------------------------------------------------

    @api.constrains('subdomain')
    def _check_subdomain(self):
        for rec in self:
            if not SUBDOMAIN_RE.match(rec.subdomain or ''):
                raise ValidationError(
                    'Subdominio inválido. Solo letras minúsculas, números '
                    'y guiones, sin empezar ni terminar con guión.'
                )

    @api.constrains('admin_password')
    def _check_password(self):
        for rec in self:
            if rec.admin_password and len(rec.admin_password) < 8:
                raise ValidationError(
                    'El password debe tener al menos 8 caracteres.'
                )

    @api.constrains('duracion')
    def _check_duracion(self):
        for rec in self:
            if rec.duracion < 1:
                raise ValidationError(
                    'La duración debe ser al menos 1 (período).'
                )

    # ------------------------------------------------------------------
    # Provisioning atómico
    # ------------------------------------------------------------------

    def action_provision_tenant(self):
        """Crea atómicamente todos los artefactos del tenant.

        Si cualquier paso falla, la transacción se rollback y nada queda
        creado. El admin del sistema puede reintentar con datos corregidos.
        """
        self.ensure_one()

        # 1. Detectar colisiones de subdominio antes de crear nada
        full_domain = '%s://%s.%s' % (
            self.domain_scheme, self.subdomain, self.base_domain,
        )
        existing_website = self.env['website'].sudo().search(
            [('domain', '=', full_domain)], limit=1,
        )
        if existing_website:
            raise UserError(
                'Ya existe un website con el dominio %s '
                '(tenant: %s).' % (
                    full_domain, existing_website.company_id.name,
                )
            )

        # 2. Detectar colisión de login del admin
        existing_user = self.env['res.users'].sudo().search(
            [('login', '=', self.admin_email)], limit=1,
        )
        if existing_user:
            raise UserError(
                'Ya existe un usuario con el email %s. '
                'Elegí otro email o reusá esa cuenta.' % self.admin_email,
            )

        # 3. Crear la company
        company_vals = {
            'name': self.name,
            'currency_id': self.currency_id.id if self.currency_id else False,
            'country_id': self.country_id.id if self.country_id else False,
            'vertical': self.vertical,
            'agenda_modo': self.agenda_modo,
        }
        company = self.env['res.company'].sudo().create(company_vals)

        # 3.1 Setear company_id en el partner asociado a la company
        # (Odoo lo crea con company_id=False por default → fuga multi-tenant)
        company.partner_id.sudo().write({
            'company_id': company.id,
            'tz': self.timezone,
        })

        # 4. Crear el website
        website_vals = {
            'name': self.name,
            'domain': full_domain,
            'company_id': company.id,
        }
        website = self.env['website'].sudo().create(website_vals)

        # 4.1 Setear company_id en el public user del website
        # (Odoo crea uno por website con company_id=False)
        if website.user_id:
            website.user_id.partner_id.sudo().write({
                'company_id': company.id,
            })

        # 5. Crear el admin user del tenant
        groups_admin = [
            self.env.ref('base.group_user').id,
            self.env.ref('innatum_agenda_core.innatum_agenda_group_admin').id,
        ]

        admin = self.env['res.users'].sudo().with_context(
            no_reset_password=True,
        ).create({
            'name': self.admin_name or self.admin_email,
            'login': self.admin_email,
            'email': self.admin_email,
            'password': self.admin_password,
            'company_id': company.id,
            'company_ids': [(6, 0, [company.id])],
            'groups_id': [(6, 0, groups_admin)],
            'tz': self.timezone,
        })

        # 5.1 Setear company_id en el partner del admin
        admin.partner_id.sudo().write({
            'company_id': company.id,
            'tz': self.timezone,
        })

        # 6. Crear la suscripción (duración interpretada según el ciclo:
        #    meses si mensual, años si anual)
        fecha_fin = self.fecha_inicio + relativedelta(months=self.duracion_meses_total)
        suscripcion = self.env['in_agenda.suscripcion'].sudo().create({
            'company_id': company.id,
            'plan_id': self.plan_id.id,
            'fecha_inicio': self.fecha_inicio,
            'fecha_fin': fecha_fin,
            'ciclo_facturacion': self.ciclo_facturacion,
            'ai_margin_pct': self.plan_id.ai_margin_pct_default,
            'state': self.state_inicial,
            'facturacion_sri_habilitada': self.facturacion_sri_habilitada,
        })

        # 5.1 Activar los add-ons seleccionados desde el inicio de la
        #     suscripción (el precio se congela del catálogo en el create).
        for addon in self.addon_ids:
            self.env['in_agenda.suscripcion.addon'].sudo().create({
                'suscripcion_id': suscripcion.id,
                'addon_id': addon.id,
                'fecha_inicio': self.fecha_inicio,
            })

        # 6.1 (Los servicios ahora son por tenant: el admin del tenant los
        # crea él mismo desde su backend tras el provisioning. Innatum ya no
        # asigna un catálogo aquí.)

        # 6.2 Crear hr.employee del admin si va a atender como profesional.
        # Caso típico: el dueño/a del tenant también atiende clientes.
        # Si destildó "El admin atiende como profesional", saltamos este
        # paso (admin solo gestiona, los profesionales se crean luego con
        # el wizard "Nuevo colaborador").
        if self.crear_empleado_admin:
            employee = self.env['hr.employee'].sudo().create({
                'name': self.admin_name or self.admin_email,
                'work_email': self.admin_email,
                'work_phone': self.admin_work_phone or False,
                'job_title': self.admin_job_title or False,
                'identification_id': self.admin_identification_id or False,
                'user_id': admin.id,
                'company_id': company.id,
            })
            _logger.info(
                'Tenant provisioning: empleado admin creado emp=%s user=%s',
                employee.id, admin.id,
            )

        # 7. Agregar la nueva company al user actual (Innatum admin) para
        # que pueda gestionar el tenant y para que el frontend no falle
        # al abrir registros de la nueva company.
        self.env.user.sudo().write({
            'company_ids': [(4, company.id)],
        })

        _logger.info(
            'Tenant provisioning OK: company=%s website=%s admin=%s susc=%s',
            company.id, website.id, admin.id, suscripcion.id,
        )

        # 8. Recargar el cliente web para que la nueva company aparezca
        # en el company switcher del user antes de navegar a la suscripción.
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }
