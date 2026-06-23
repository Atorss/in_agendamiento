# -*- coding: utf-8 -*-

import logging
import uuid

from dateutil.relativedelta import relativedelta

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)


class InAgendaSuscripcion(models.Model):
    """Suscripción SaaS de un tenant (1 por res.company).

    Vínculo entre una company (tenant) y un plan, con fechas de vigencia,
    margen IA snapshotteado y un identificador externo (external_ref)
    estable que sobrevive entre BDs — útil para futura agregación
    cross-shard en un warehouse.
    """
    _name = 'in_agenda.suscripcion'
    _description = 'Suscripción SaaS de tenant'
    _order = 'fecha_inicio desc, id desc'
    _rec_name = 'name'

    name = fields.Char(
        string='Referencia', required=True, copy=False,
        readonly=True, default='Nueva',
    )
    external_ref = fields.Char(
        string='Ref. externa', required=True, copy=False, readonly=True,
        default=lambda self: uuid.uuid4().hex,
        index=True,
        help='Identificador estable e inmutable. Sirve para agregación '
             'cross-BD a un warehouse externo. NUNCA debe modificarse '
             'después de creado.',
    )
    company_id = fields.Many2one(
        'res.company', string='Tenant (company)', required=True,
        ondelete='restrict', index=True,
    )
    plan_id = fields.Many2one(
        'in_agenda.plan', string='Plan', required=True, ondelete='restrict',
    )
    fecha_inicio = fields.Date(
        string='Inicio', required=True, default=fields.Date.today,
    )
    fecha_fin = fields.Date(
        string='Fin', required=True,
        help='Fecha de vencimiento. Un cron diario marca como "expired" las '
             'suscripciones con fecha_fin pasada.',
    )
    ai_margin_pct = fields.Float(
        string='Margen IA (%)', digits=(5, 2), default=50.0,
        help='Margen de Innatum sobre recargas IA. Snapshot del plan al '
             'crear la suscripción; puede ajustarse manualmente después.',
    )
    ciclo_facturacion = fields.Selection([
        ('mensual', 'Mensual'),
        ('anual', 'Anual'),
    ], string='Ciclo de facturación', default='mensual', required=True,
        tracking=True,
        help='Cómo paga el tenant. El anual aplica el descuento del plan.')
    precio_aplicado_usd = fields.Float(
        string='Precio plan (USD)', compute='_compute_precio_aplicado',
        store=True, digits=(12, 2),
        help='Precio del PLAN BASE según el ciclo: mensual, o anual con el '
             'descuento del plan. No incluye add-ons.')

    # --- Funcionalidad gratuita (no add-on de cobro): solo un check ---
    facturacion_sri_habilitada = fields.Boolean(
        string='Facturación electrónica (SRI)', default=False, tracking=True,
        help='Funcionalidad GRATUITA: emisión de comprobantes electrónicos al '
             'SRI. No es un add-on de cobro, es solo habilitar la función.')

    # --- Add-ons de COBRO activados por cliente (catálogo, vigencia por fechas) ---
    addon_ids = fields.One2many(
        'in_agenda.suscripcion.addon', 'suscripcion_id', string='Add-ons',
        help='Add-ons de pago activados para este tenant (IA web, WhatsApp), '
             'con su período de vigencia. Permite activarlos a mitad de la '
             'suscripción.')
    precio_addons_usd = fields.Float(
        string='Add-ons (período, USD)', compute='_compute_precio_addons',
        store=True, digits=(12, 2),
        help='Suma de los add-ons VIGENTES hoy, según el ciclo (precio '
             'mensual o anual del add-on).')
    precio_total_usd = fields.Float(
        string='Total del período (USD)', compute='_compute_precio_total',
        store=True, digits=(12, 2),
        help='Plan base + add-ons vigentes, según el ciclo.')

    # --- Servicios del catálogo habilitados para el tenant (M2M inverso a
    #     servicio.company_ids). Permite ver/agregar/quitar desde la suscripción. ---
    servicio_ids = fields.Many2many(
        'innatum.agenda.servicio', string='Servicios habilitados',
        compute='_compute_servicio_ids', inverse='_inverse_servicio_ids',
        help='Servicios del catálogo Innatum habilitados para este tenant. '
             'No se puede quitar un servicio que ya tiene planificaciones '
             'creadas para el tenant.')

    state = fields.Selection([
        ('trial', 'Trial'),
        ('active', 'Activa'),
        ('suspended', 'Suspendida'),
        ('cancelled', 'Cancelada'),
        ('expired', 'Vencida'),
    ], string='Estado', default='active', required=True, tracking=True)
    recarga_ids = fields.One2many(
        'in_agenda.recarga_ia', 'suscripcion_id',
        string='Recargas IA',
    )
    recarga_count = fields.Integer(
        compute='_compute_recarga_aggregates',
    )
    tokens_disponibles_total_usd = fields.Float(
        string='Disponibles total (USD)',
        compute='_compute_recarga_aggregates', digits=(12, 4),
    )
    tokens_consumidos_total_usd = fields.Float(
        string='Consumidos total (USD)',
        compute='_compute_recarga_aggregates', digits=(12, 4),
    )
    tokens_restantes_total_usd = fields.Float(
        string='Restantes total (USD)',
        compute='_compute_recarga_aggregates', digits=(12, 4),
    )
    notes = fields.Text(string='Notas internas')
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('external_ref_unique', 'unique(external_ref)',
         'La referencia externa debe ser única.'),
        ('company_id_unique', 'unique(company_id)',
         'Ya existe una suscripción para esta company.'),
    ]

    @api.depends('recarga_ids', 'recarga_ids.tokens_disponibles_usd',
                 'recarga_ids.tokens_consumidos_usd',
                 'recarga_ids.tokens_restantes_usd')
    def _compute_recarga_aggregates(self):
        for rec in self:
            recs = rec.recarga_ids
            rec.recarga_count = len(recs)
            rec.tokens_disponibles_total_usd = sum(recs.mapped('tokens_disponibles_usd'))
            rec.tokens_consumidos_total_usd = sum(recs.mapped('tokens_consumidos_usd'))
            rec.tokens_restantes_total_usd = sum(recs.mapped('tokens_restantes_usd'))

    @api.depends('plan_id', 'ciclo_facturacion',
                 'plan_id.precio_mensual_usd', 'plan_id.precio_anual_usd')
    def _compute_precio_aplicado(self):
        for rec in self:
            if rec.ciclo_facturacion == 'anual':
                rec.precio_aplicado_usd = rec.plan_id.precio_anual_usd
            else:
                rec.precio_aplicado_usd = rec.plan_id.precio_mensual_usd

    @api.depends('addon_ids', 'addon_ids.precio_mensual_usd',
                 'addon_ids.precio_anual_usd', 'addon_ids.fecha_inicio',
                 'addon_ids.fecha_fin', 'ciclo_facturacion')
    def _compute_precio_addons(self):
        today = fields.Date.today()
        for rec in self:
            total = 0.0
            for line in rec.addon_ids:
                vigente = (line.fecha_inicio and line.fecha_inicio <= today
                           and (not line.fecha_fin or line.fecha_fin >= today))
                if vigente:
                    total += (line.precio_anual_usd if rec.ciclo_facturacion == 'anual'
                              else line.precio_mensual_usd)
            rec.precio_addons_usd = total

    @api.depends('precio_aplicado_usd', 'precio_addons_usd')
    def _compute_precio_total(self):
        for rec in self:
            # precio_aplicado y precio_addons ya están en la unidad del ciclo
            # (ambos mensual, o ambos anual), así que es suma directa.
            rec.precio_total_usd = rec.precio_aplicado_usd + rec.precio_addons_usd

    @api.depends('company_id')
    def _compute_servicio_ids(self):
        Serv = self.env['innatum.agenda.servicio'].sudo()
        for rec in self:
            rec.servicio_ids = Serv.search(
                [('company_ids', 'in', rec.company_id.id)]) if rec.company_id else False

    def _inverse_servicio_ids(self):
        """Sincroniza servicio.company_ids con la company del tenant.
        Al QUITAR un servicio, valida que no tenga planificaciones creadas
        para este tenant (si las tiene, bloquea)."""
        Serv = self.env['innatum.agenda.servicio'].sudo()
        Config = self.env['innatum.agenda.config'].sudo()
        for rec in self:
            company = rec.company_id
            if not company:
                continue
            deseados = rec.servicio_ids
            actuales = Serv.search([('company_ids', 'in', company.id)])
            for s in (actuales - deseados):
                n_plan = Config.search_count([
                    ('company_id', '=', company.id),
                    ('servicio_ids', 'in', s.id),
                ])
                if n_plan:
                    raise ValidationError(_(
                        'No se puede quitar el servicio «%(serv)s»: ya tiene '
                        '%(n)d planificación(es) creada(s) para este tenant. '
                        'Elimina primero esas planificaciones.',
                        serv=s.name, n=n_plan,
                    ))
                s.write({'company_ids': [(3, company.id)]})
            for s in (deseados - actuales):
                s.write({'company_ids': [(4, company.id)]})

    @api.onchange('fecha_inicio', 'ciclo_facturacion')
    def _onchange_vigencia(self):
        """Deriva fecha_fin del ciclo: mensual = +1 mes, anual = +12 meses."""
        if self.fecha_inicio:
            meses = 12 if self.ciclo_facturacion == 'anual' else 1
            self.fecha_fin = self.fecha_inicio + relativedelta(months=meses)

    @api.constrains('fecha_inicio', 'fecha_fin')
    def _check_fechas(self):
        for rec in self:
            if rec.fecha_fin < rec.fecha_inicio:
                raise ValidationError(
                    'La fecha "Fin" debe ser mayor o igual a "Inicio".'
                )

    @api.constrains('ai_margin_pct')
    def _check_margin(self):
        for rec in self:
            if not (0 <= rec.ai_margin_pct <= 100):
                raise ValidationError(
                    'El margen IA debe estar entre 0 y 100%.'
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nueva') == 'Nueva':
                seq = self.env['ir.sequence'].next_by_code('in_agenda.suscripcion')
                vals['name'] = seq or 'SUSC/0001'
        return super().create(vals_list)

    def write(self, vals):
        # external_ref es inmutable después de creado
        if 'external_ref' in vals:
            for rec in self:
                if rec.external_ref and vals.get('external_ref') != rec.external_ref:
                    raise UserError(_(
                        'external_ref es inmutable. No se puede modificar '
                        'una vez creada la suscripción.'
                    ))
        return super().write(vals)

    # ------------------------------------------------------------------
    # API pública para el gate IA
    # ------------------------------------------------------------------

    @api.model
    def _get_for_company(self, company):
        """Devuelve la suscripción activa de una company, o empty recordset.

        El gate IA usa esto antes de cada llamada para verificar saldo.
        Corre con sudo porque el caller (engine IA) puede no tener acceso
        directo al modelo de suscripciones (es de Innatum).
        """
        if not company:
            return self.browse()
        return self.sudo().search([
            ('company_id', '=', company.id),
            ('state', 'in', ('trial', 'active')),
            ('active', '=', True),
        ], limit=1)

    @api.model
    def _ensure_active_for_company(self, company):
        """Devuelve la suscripción activa o lanza ValidationError.

        Garantía estructural: en producción, toda tenant company debe nacer
        con una suscripción activa (el wizard de provisioning lo hace). Si
        algún check de límites (max_profesionales, max_turnos_mes) detecta
        que no hay suscripción activa, es un error operativo serio que debe
        bloquear la operación.

        Excepción: la company del sistema (base.main_company, típicamente
        "My Company") no opera como tenant y queda sin límites. Devuelve
        False para señalar "sin límites".
        """
        if not company:
            raise ValidationError(_(
                'No se puede determinar la empresa de este registro.'
            ))
        main_company = self.env.ref('base.main_company', raise_if_not_found=False)
        if main_company and company == main_company:
            return False  # sistema: sin límites
        susc = self._get_active_for_company(company)
        if not susc:
            raise ValidationError(_(
                'La empresa "%(name)s" no tiene una suscripción SaaS '
                'activa. Contacta a Innatum para regularizar antes de '
                'continuar operando.',
                name=company.name,
            ))
        return susc

    @api.model
    def _get_active_for_company(self, company):
        """Idéntico a _get_for_company. Nombre más explícito para call sites
        de límites operativos (vs gate IA).
        """
        return self._get_for_company(company)

    # Claves de feature válidas. Cada una corresponde al `code` de un add-on
    # del catálogo (in_agenda.addon). Las features se activan por períodos en
    # las líneas addon_ids; el gate mira si HOY hay una línea vigente.
    _FEATURE_KEYS = ('ia_web', 'whatsapp', 'facturacion_sri')

    def _has_feature(self, key):
        """True si ESTA suscripción (activa) tiene el add-on `key` VIGENTE hoy.

        Una suscripción no activa (suspended/cancelled/expired) no habilita
        ninguna feature. La vigencia se evalúa por las fechas de la línea
        (ej. WhatsApp activado desde marzo no aplica en febrero).
        """
        self.ensure_one()
        if key not in self._FEATURE_KEYS:
            raise ValidationError(_('Feature desconocida: %s') % key)
        if self.state not in ('trial', 'active') or not self.active:
            return False
        # Facturación SRI es gratuita: un check simple, no add-on con fechas.
        if key == 'facturacion_sri':
            return self.facturacion_sri_habilitada
        # IA web / WhatsApp: add-ons de cobro, vigentes por fecha de la línea.
        today = fields.Date.today()
        return any(
            line.code == key
            and line.fecha_inicio and line.fecha_inicio <= today
            and (not line.fecha_fin or line.fecha_fin >= today)
            for line in self.addon_ids
        )

    @api.model
    def _company_has_feature(self, company, key):
        """True si la company tiene una suscripción activa con el add-on `key`
        vigente hoy.

        Punto de entrada único para los gates server-side (webhook WhatsApp,
        facturación SRI, chatbot web). La company del sistema
        (base.main_company) no opera como tenant: tiene todas las features.
        """
        if key not in self._FEATURE_KEYS:
            raise ValidationError(_('Feature desconocida: %s') % key)
        if not company:
            return False
        main_company = self.env.ref('base.main_company', raise_if_not_found=False)
        if main_company and company == main_company:
            return True  # sistema: sin restricciones
        susc = self._get_for_company(company)
        return bool(susc) and susc._has_feature(key)

    @api.model
    def _has_ai_credit_for_company(self, company):
        """Devuelve True si la company tiene saldo IA disponible.

        Usado para decidir si renderizar el widget del chatbot en el
        sitio público del tenant. Evita mostrar el ícono cuando el
        cliente final no podría usarlo (mejor UX: no aparece > aparece
        y tira error).

        Criterios:
        - Existe suscripción activa (trial/active)
        - El add-on IA web está vigente hoy en la suscripción
        - Suma de tokens_restantes_usd > 0
        """
        if not company:
            return False
        susc = self._get_for_company(company)
        if not susc:
            return False
        if not susc._has_feature('ia_web'):
            return False
        return susc.tokens_restantes_total_usd > 0

    def action_view_recargas(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Recargas IA — %s') % self.name,
            'res_model': 'in_agenda.recarga_ia',
            'view_mode': 'list,form',
            'domain': [('suscripcion_id', '=', self.id)],
            'context': {'default_suscripcion_id': self.id},
        }

    # ------------------------------------------------------------------
    # Cron de vencimiento
    # ------------------------------------------------------------------

    @api.model
    def _cron_verificar_vencimiento(self):
        """Marca como 'expired' las suscripciones vencidas.

        Se ejecuta diariamente. NO desactiva users del tenant
        automáticamente para evitar lockout accidental — eso queda como
        decisión manual del admin Innatum vía botón en el form.
        """
        hoy = fields.Date.today()
        vencidas = self.search([
            ('state', 'in', ('trial', 'active')),
            ('fecha_fin', '<', hoy),
        ])
        if vencidas:
            vencidas.write({'state': 'expired'})
            _logger.info(
                'Cron suscripcion: %d suscripciones marcadas como expired',
                len(vencidas),
            )
        return True
