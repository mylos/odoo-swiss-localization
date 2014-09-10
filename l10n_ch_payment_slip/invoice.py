# -*- coding: utf-8 -*-
##############################################################################
#
#    Author: Nicolas Bessi. Copyright Camptocamp SA
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################
import re

from openerp.osv.orm import Model
from openerp.osv import fields
from openerp.tools import mod10r
from openerp.tools.translate import _

class AccountMoveLine(Model):

    _inherit = "account.move.line"

    _compile_get_ref = re.compile('[^0-9]')

    _columns = {
        'transaction_ref': fields.char('Transaction Ref.', size=128),
    }

    def get_bvr_ref(self, cursor, uid, move_line_id, context=None):
        """Retrieve ESR/BVR reference from move line in order to print it

        Returns False when no BVR reference should be generated.  No
        reference is generated when a transaction reference already
        exists for the line (likely been generated by a payment service).
        """
        res = ''
        if isinstance(move_line_id, (tuple, list)):
            assert len(move_line_id) == 1, "Only 1 ID expected"
            move_line_id = move_line_id[0]
        move_line = self.browse(cursor, uid, move_line_id, context=context)
        ## We check if the type is bvr, if not we return false
        if move_line.invoice.partner_bank_id.state != 'bvr':
            return ''
        ##
        if move_line.invoice.partner_bank_id.bvr_adherent_num:
            res = move_line.invoice.partner_bank_id.bvr_adherent_num
        move_number = ''
        if move_line.invoice.number:
            move_number = self._compile_get_ref.sub('', str(move_line.invoice.number) + str(move_line_id))
        reference = mod10r(res + move_number.rjust(26 - len(res), '0'))
        if (move_line.transaction_ref and
                move_line.transaction_ref != reference):
            # the line has already a transaction id and it is not
            # a BVR reference
            return ''
        return reference


class AccountInvoice(Model):
    """Inherit account.invoice in order to add bvr
    printing functionnalites. BVR is a Swiss payment vector"""
    _inherit = "account.invoice"

    _compile_get_ref = re.compile('[^0-9]')

    def _get_reference_type(self, cursor=False, user=False, context=None):
       """Function use by the function field reference_type in order to initalise available
       BVR Reference Types"""
       res = [('none', _('Free Reference')), ('bvr', _('BVR'))]
       return res
  
    def _compute_full_bvr_name(self, cursor, uid, ids, field_names, arg, context=None):
        res = {}
        move_line_obj = self.pool.get('account.move.line')
        account_obj = self.pool.get('account.account')
        tier_account_id = account_obj.search(cursor, uid, [('type', 'in', ['receivable', 'payable'])])
        for inv in self.browse(cursor, uid, ids, context=context):
            move_lines = move_line_obj.search(cursor, uid, [('move_id', '=', inv.move_id.id),
                                                            ('account_id', 'in', tier_account_id)])
            if move_lines:
                if len(move_lines) == 1:
                    res[inv.id] = self._space(inv.get_bvr_ref())
                else:
                    refs = []
                    for move_line in move_line_obj.browse(cursor, uid, move_lines, context=context):
                        refs.append(self._space(move_line.get_bvr_ref()))
                    res[inv.id] = ' ; '.join(refs)
        return res

    _columns = {
        ### BVR reference type BVR or FREE
        'reference_type': fields.selection(_get_reference_type,
                                           'Reference Type', required=True),
        ### Partner bank link between bank and partner id
        'partner_bank_id': fields.many2one('res.partner.bank', 'Bank Account',
                                           help='The partner bank account to pay\nKeep empty to use the default'),
        'bvr_reference': fields.function(_compute_full_bvr_name, type="char", size=512, string="BVR REF.",
                                         store=True, readonly=True)
    }

    def _get_bvr_ref(self, cr, uid, invoice, context=None):
        """Retrieve ESR/BVR reference form invoice in order to print it

        Receive a browse record so it can be overloaded without rebrowsing
        the invoice.
        """
        res = ''
        ## We check if the type is bvr, if not we return false
        if invoice.partner_bank_id.state != 'bvr':
            return ''
        ##
        if invoice.partner_bank_id.bvr_adherent_num:
            res = invoice.partner_bank_id.bvr_adherent_num
        invoice_number = ''
        if invoice.number:
            invoice_number = self._compile_get_ref.sub('', invoice.number)
        return mod10r(res + invoice_number.rjust(26 - len(res), '0'))

    def get_bvr_ref(self, cursor, uid, inv_id, context=None):
        """Retrieve ESR/BVR reference form invoice in order to print it

        Returns False when no BVR reference should be generated.  No
        reference is generated when the invoice is not a BVR invoice.
        """
        if isinstance(inv_id, (list, tuple)):
            assert len(inv_id) == 1, "1 ID expected, got %s" % inv_id
            inv_id = inv_id[0]
        inv = self.browse(cursor, uid, inv_id, context=context)
        return self._get_bvr_ref(cursor, uid, inv, context=context)

    def _space(self, nbr, nbrspc=5):
        """Spaces * 5.

        Example:
            self._space('123456789012345')
            '12 34567 89012 345'
        """
        return ''.join([' '[(i - 2) % nbrspc:] + c for i, c in enumerate(nbr)])

    def _update_ref_on_account_analytic_line(self, cr, uid, ref, move_id, context=None):
        cr.execute('UPDATE account_analytic_line SET ref=%s'
                   '   FROM account_move_line '
                   ' WHERE account_move_line.move_id = %s '
                   '   AND account_analytic_line.move_id = account_move_line.id',
                   (ref, move_id))
        return True

    def _action_bvr_number_move_line(self, cr, uid, invoice, move_line,
                                     ref, context=None):
        if not ref:
            return
        cr.execute('UPDATE account_move_line SET transaction_ref=%s'
                   '  WHERE id=%s', (ref, move_line.id))
        self._update_ref_on_account_analytic_line(cr, uid, ref,
                                                  move_line.move_id.id)

    def action_number(self, cr, uid, ids, context=None):
        """ Copy the BVR/ESR reference in the transaction_ref of move lines.

        For customers invoices: the BVR reference is computed using
        ``get_bvr_ref()`` on the invoice or move lines.

        For suppliers invoices: the BVR reference is stored in the reference
        field of the invoice.

        """
        res = super(AccountInvoice, self).action_number(cr, uid, ids, context=context)
        move_line_obj = self.pool.get('account.move.line')

        for inv in self.browse(cr, uid, ids, context=context):
            move_line_ids = move_line_obj.search(
                cr, uid,
                [('move_id', '=', inv.move_id.id),
                 ('account_id', '=', inv.account_id.id)],
                context=context)
            if not move_line_ids:
                continue
            move_lines = move_line_obj.browse(cr, uid, move_line_ids,
                                              context=context)
            for move_line in move_lines:
                if inv.type in ('out_invoice', 'out_refund'):
                    if len(move_lines) == 1:
                        # We keep this branch for compatibility with single
                        # BVR report.
                        # This should be cleaned when porting to V8
                        ref = inv.get_bvr_ref()
                    else:
                        ref = move_line.get_bvr_ref()
                elif inv.reference_type == 'bvr' and inv.reference:
                    ref = inv.reference
                else:
                    ref = False
                self._action_bvr_number_move_line(cr, uid, inv,
                                                  move_line, ref,
                                                  context=context)
        return res

    def copy(self, cursor, uid, inv_id, default=None, context=None):
        default = default or {}
        default.update({'reference': False})
        return super(AccountInvoice, self).copy(cursor, uid, inv_id, default, context)


class AccountTaxCode(Model):
    """Inherit account tax code in order
    to add a Case code"""
    _name = 'account.tax.code'
    _inherit = "account.tax.code"
    _columns = {
        'code': fields.char('Case Code', size=512),
    }
# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
