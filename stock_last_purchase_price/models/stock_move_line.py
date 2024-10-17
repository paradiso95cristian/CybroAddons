# -*- coding: utf-8 -*-
################################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#    Copyright (C) 2024-TODAY Cybrosys Technologies(<https://www.cybrosys.com>).
#    Author: Fathima Mazlin AM(odoo@cybrosys.com)
#
#    This program is free software: you can modify
#    it under the terms of the GNU Affero General Public License (AGPL) as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
################################################################################
from odoo import models


class StockMoveLine(models.Model):
    """ Class to inherit the model stock.move.line to override the create
    function """
    _inherit = 'stock.move.line'

    def write(self, vals):
        """ When editing a done stock.move.line, we impact the valuation.
        Users may increase or decrease the `qty_done` field. There are three
        cost method available: standard, average and fifo. We implement the
        logic in a similar way for standard and average: increase or decrease
        the original value with the standard or average price of today. In
        fifo, we have a different logic whether the move is incoming or
        outgoing. If the move is incoming, we update the value and
        remaining_value/qty with the unit price of the move. If the move is
        outgoing and the user increases qty_done, we call _run_fifo, and it'll
        consume layer(s) in the stack the same way a new outgoing move would
        have done. If the move is outgoing and the user decreases qty_done, we
        either increase the last receipt candidate if one is found or we
        decrease the value with the last fifo price.
        """
        if 'qty_done' in vals:
            moves_to_update = {}
            for move_line in self.filtered(
                    lambda ml: ml.state == 'done' and (
                            ml.move_id._is_in() or ml.move_id._is_out())):
                moves_to_update[move_line.move_id] = (
                        vals['qty_done'] - move_line.qty_done)
            for move_id, qty_difference in moves_to_update.items():
                move_vals = {}
                if move_id.product_id.cost_method in ['standard', 'average',
                                                      'last']:
                    correction_value = (qty_difference *
                                        move_id.product_id.standard_price)
                    if move_id._is_in():
                        move_vals['value'] = move_id.value + correction_value
                    elif move_id._is_out():
                        move_vals['value'] = move_id.value - correction_value
                else:
                    if move_id._is_in():
                        correction_value = qty_difference * move_id.price_unit
                        move_vals['value'] = move_id.value + correction_value
                        move_vals['remaining_qty'] = (move_id.remaining_qty +
                                                      qty_difference)
                        move_vals['remaining_value'] = (move_id.remaining_value
                                                        + correction_value)
                    elif move_id._is_out() and qty_difference > 0:
                        correction_value = self.env['stock.move']._run_fifo(
                            move_id, quantity=qty_difference)
                        # No need to adapt `remaining_qty` and
                        # `remaining_value` as `_run_fifo` took care of it
                        move_vals['value'] = move_id.value - correction_value
                    elif move_id._is_out() and qty_difference < 0:
                        candidates_receipt = self.env['stock.move'].search(
                            move_id._get_in_domain(), order='date, id desc',
                            limit=1)
                        if candidates_receipt:
                            candidates_receipt.write({
                                'remaining_qty': candidates_receipt.remaining_qty + -qty_difference,
                                'remaining_value': candidates_receipt.remaining_value + (
                                        -qty_difference * candidates_receipt.price_unit),
                            })
                            correction_value = (qty_difference *
                                                candidates_receipt.price_unit)
                        else:
                            correction_value = (qty_difference *
                                                move_id.product_id.standard_price)
                        move_vals['value'] = move_id.value - correction_value
                move_id.write(move_vals)
                if move_id.product_id.valuation == 'real_time':
                    move_id.with_context(
                        force_valuation_amount=correction_value,
                        forced_quantity=qty_difference)._account_entry_move()
                if qty_difference > 0:
                    move_id.product_price_update_before_done(
                        forced_qty=qty_difference)
        return super(StockMoveLine, self).write(vals)
