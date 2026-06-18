# -*- coding: utf-8 -*-

import logging
import uuid

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

    @api.model
    def _has_ai_credit_for_company(self, company):
        """Devuelve True si la company tiene saldo IA disponible.

        Usado para decidir si renderizar el widget del chatbot en el
        sitio público del tenant. Evita mostrar el ícono cuando el
        cliente final no podría usarlo (mejor UX: no aparece > aparece
        y tira error).

        Criterios:
        - Existe suscripción activa (trial/active)
        - Plan tiene ai_enabled=True
        - Suma de tokens_restantes_usd > 0
        """
        if not company:
            return False
        susc = self._get_for_company(company)
        if not susc:
            return False
        if not susc.plan_id.ai_enabled:
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
