from odoo import http
from odoo.http import request
import json

class AILiveBotController(http.Controller):
    
    @http.route('/ai_livebot/chat', type='json', auth='user', methods=['POST'])
    def chat(self, message, channel_id):
        """Endpoint per inviare messaggi alla chat AI"""
        try:
            channel = request.env['discuss.channel'].browse(channel_id)
            if not channel.exists():
                return {'error': 'Channel not found'}
            
            # Il messaggio viene gestito dal message_post override
            channel.message_post(
                body=message,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )
            
            return {'success': True}
            
        except Exception as e:
            return {'error': str(e)}
    
    @http.route('/ai_livebot/warehouse/stock', type='json', auth='user', methods=['GET'])
    def get_stock(self, product_name=None, product_id=None):
        """Endpoint per ottenere info sullo stock"""
        warehouse_ops = request.env['warehouse.operations']
        return warehouse_ops.get_stock_info(product_name=product_name, product_id=product_id)
    
    @http.route('/ai_livebot/warehouse/orders', type='json', auth='user', methods=['GET'])
    def get_orders(self, limit=10):
        """Endpoint per ottenere ordini pendenti"""
        warehouse_ops = request.env['warehouse.operations']
        return warehouse_ops.get_pending_orders(limit=limit)
    
    @http.route('/ai_livebot/warehouse/validate', type='json', auth='user', methods=['POST'])
    def validate_order(self, picking_id):
        """Endpoint per validare un ordine"""
        warehouse_ops = request.env['warehouse.operations']
        return warehouse_ops.validate_delivery(picking_id)
