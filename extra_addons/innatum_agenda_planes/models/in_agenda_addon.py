# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class InAgendaAddon(models.Model):
    """Catálogo de add-ons del SaaS. Innatum configura aquí el precio
    mensual/anual de cada add-on (o lo marca gratis). En la suscripción de
    cada tenant se activan por períodos (in_agenda.suscripcion.addon)."""
    _name = 'in_agenda.addon'
    _description = 'Catálogo de add-ons SaaS'
    _order = 'sequence, name'

    name = fields.Char(string='Nombre', required=True)
    code = fields.Char(
        string='Código', required=True,
        help='Clave del gate de feature. Debe ser uno de: ia_web, whatsapp, '
             'facturacion_sri.')
    sequence = fields.Integer(default=10)
    es_gratis = fields.Boolean(
        string='Gratis (solo activar)', default=False,
        help='Si está activo, el add-on no tiene costo: en la suscripción es '
             'solo agregarlo. Caso: facturación electrónica SRI.')
    precio_mensual_usd = fields.Float(string='Precio mensual (USD)', digits=(12, 2))
    precio_anual_usd = fields.Float(string='Precio anual (USD)', digits=(12, 2))
    descripcion = fields.Text(string='Descripción')
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('code_unique', 'unique(code)', 'El código del add-on debe ser único.'),
    ]

    @api.onchange('es_gratis')
    def _onchange_es_gratis(self):
        if self.es_gratis:
            self.precio_mensual_usd = 0.0
            self.precio_anual_usd = 0.0


class InAgendaSuscripcionAddon(models.Model):
    """Add-on activado en una suscripción, con período de vigencia.

    Permite activar un add-on a mitad de la suscripción (ej. WhatsApp desde
    marzo aunque la suscripción inició en enero) y darlo de baja después. El
    precio se CONGELA del catálogo al activar (no cambia si luego sube el
    catálogo). El gate de feature mira si HOY cae dentro de una línea vigente."""
    _name = 'in_agenda.suscripcion.addon'
    _description = 'Add-on activado en suscripción (por períodos)'
    _order = 'fecha_inicio desc, id desc'

    suscripcion_id = fields.Many2one(
        'in_agenda.suscripcion', string='Suscripción', required=True,
        ondelete='cascade', index=True)
    company_id = fields.Many2one(
        'res.company', related='suscripcion_id.company_id', store=True, index=True)
    addon_id = fields.Many2one(
        'in_agenda.addon', string='Add-on', required=True, ondelete='restrict')
    code = fields.Char(related='addon_id.code', store=True, string='Código')
    fecha_inicio = fields.Date(
        string='Desde', required=True, default=fields.Date.today)
    fecha_fin = fields.Date(
        string='Hasta', help='Vacío = vigente indefinidamente.')
    es_gratis = fields.Boolean(string='Gratis')
    precio_mensual_usd = fields.Float(
        string='Precio mensual (USD)', digits=(12, 2),
        help='Congelado del catálogo al activar.')
    precio_anual_usd = fields.Float(
        string='Precio anual (USD)', digits=(12, 2),
        help='Congelado del catálogo al activar.')
    activo_hoy = fields.Boolean(
        string='Vigente hoy', compute='_compute_activo_hoy')

    @api.depends('fecha_inicio', 'fecha_fin')
    def _compute_activo_hoy(self):
        today = fields.Date.today()
        for rec in self:
            rec.activo_hoy = bool(
                rec.fecha_inicio and rec.fecha_inicio <= today
                and (not rec.fecha_fin or rec.fecha_fin >= today))

    @api.onchange('addon_id')
    def _onchange_addon_id(self):
        """Congela el precio del catálogo al elegir el add-on."""
        if self.addon_id:
            self.es_gratis = self.addon_id.es_gratis
            self.precio_mensual_usd = self.addon_id.precio_mensual_usd
            self.precio_anual_usd = self.addon_id.precio_anual_usd

    @api.model_create_multi
    def create(self, vals_list):
        # Congelar precio del catálogo si no vino explícito (ej. creado por
        # el wizard o por código).
        for vals in vals_list:
            if vals.get('addon_id') and 'precio_mensual_usd' not in vals:
                addon = self.env['in_agenda.addon'].browse(vals['addon_id'])
                vals.setdefault('precio_mensual_usd', addon.precio_mensual_usd)
                vals.setdefault('precio_anual_usd', addon.precio_anual_usd)
                vals.setdefault('es_gratis', addon.es_gratis)
        return super().create(vals_list)

    @api.constrains('fecha_inicio', 'fecha_fin')
    def _check_fechas(self):
        for rec in self:
            if rec.fecha_fin and rec.fecha_fin < rec.fecha_inicio:
                raise ValidationError(
                    'La fecha "Hasta" del add-on no puede ser anterior a "Desde".')
