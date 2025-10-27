from odoo import models, api
import json
import logging

_logger = logging.getLogger(__name__)

class WarehouseOperations(models.AbstractModel):
    _name = 'warehouse.operations'
    _description = 'Warehouse Operations for AI'
    
    @api.model
    def get_stock_info(self, product_name=None, product_id=None):
        """Ottiene informazioni sullo stock di un prodotto"""
        Product = self.env['product.product']
        
        if product_id:
            product = Product.browse(product_id)
        elif product_name:
            product = Product.search([('name', 'ilike', product_name)], limit=1)
        else:
            return {"error": "Specificare product_name o product_id"}
        
        if not product:
            return {"error": f"Prodotto '{product_name}' non trovato"}
        
        return {
            "product_id": product.id,
            "product_name": product.name,
            "qty_available": product.qty_available,
            "virtual_available": product.virtual_available,
            "incoming_qty": product.incoming_qty,
            "outgoing_qty": product.outgoing_qty,
        }
    
    @api.model
    def search_products(self, search_term=None, limit=50):
        """Cerca prodotti nel catalogo; se search_term non e fornito restituisce i primi prodotti"""
        Product = self.env['product.product']
        domain = [('name', 'ilike', search_term)] if search_term else []
        products = Product.search(domain, limit=limit)
        
        
        def _price(p):
            # list_price sta su product.template
            return getattr(p, 'lst_price', False) or p.product_tmpl_id.list_price

        return [{
            "id": p.id,
            "name": p.name,
            "qty_available": p.qty_available,
            "default_code": p.default_code or "",
            "list_price": _price(p),
        } for p in products]

    @api.model
    def get_pending_orders(self, order_type=None, limit=10):
        """
        Ottiene gli ordini in sospeso filtrabili per tipo: 'incoming' o 'outgoing'.
        """
        StockPicking = self.env['stock.picking']
        domain = [('state', 'in', ['assigned', 'waiting', 'confirmed'])]

        if order_type in ('incoming', 'outgoing'):
            domain.append(('picking_type_id.code', '=', order_type))

        pickings = StockPicking.search(domain, limit=limit, order='scheduled_date desc')

        def fmt(picking):
            scheduled = picking.scheduled_date.strftime("%Y-%m-%d %H:%M") if picking.scheduled_date else None
            return {
                "id": picking.id,
                "name": picking.name,
                "partner": picking.partner_id.name or "N/D",
                "state": picking.state,
                "scheduled_date": scheduled,
                "origin": picking.origin or "",
            }

        return [fmt(p) for p in pickings]
    
    @api.model
    def get_delivery_details(self, picking_name=None, picking_id=None):
        """
        Ottiene i dettagli completi di un Delivery/Transfer, inclusi tutti i movimenti con move_id.
        Utile per sapere quali prodotti sono nell'ordine prima di modificarlo.
        
        Args:
            picking_name (str): Nome del delivery (es. "WH/OUT/00013")
            picking_id (int): ID del picking (alternativa a picking_name)
        
        Returns:
            Dict con dettagli delivery e lista movimenti completa di move_id
        """
        StockPicking = self.env['stock.picking']
        
        # Trova il picking
        if picking_id:
            picking = StockPicking.browse(picking_id)
        elif picking_name:
            picking = StockPicking.search([('name', '=', picking_name)], limit=1)
        else:
            return {"error": "Specificare picking_name o picking_id"}
        
        if not picking.exists():
            return {"error": f"Delivery '{picking_name or picking_id}' non trovato"}
        
        # Prepara lista movimenti
        moves = []
        for move in picking.move_ids:
            moves.append({
                "move_id": move.id,
                "product_id": move.product_id.id,
                "product_name": move.product_id.name,
                "product_code": move.product_id.default_code or "",
                "demand": move.product_uom_qty, 
                "quantity": getattr(move, 'quantity', None) if hasattr(move, '_fields') and 'quantity' in move._fields else
                            sum(ml.quantity for ml in move.move_line_ids if hasattr(ml, 'quantity')),
                "reserved": sum(ml.quantity for ml in move.move_line_ids if hasattr(ml, 'quantity')),
                "uom": move.product_uom.name,
                "state": move.state,
                "is_done": move.state == 'done',
            })
        
        return {
            "picking_id": picking.id,
            "picking_name": picking.name,
            "partner_id": picking.partner_id.id,
            "partner_name": picking.partner_id.name,
            "state": picking.state,
            "state_display": dict(picking._fields['state'].selection).get(picking.state),
            "scheduled_date": picking.scheduled_date.strftime("%Y-%m-%d %H:%M") if picking.scheduled_date else None,
            "origin": picking.origin or "",
            "moves": moves,
            "moves_count": len(moves)
        }
    
    @api.model
    def validate_delivery(self, picking_id=None, picking_name=None):
        """
        Valida/Evade un ordine di consegna (spedizione fisica).
        
        Args:
            picking_id (int): ID del picking (es. 35)
            picking_name (str): Nome del picking (es. "WH/OUT/00035")
        """
        StockPicking = self.env['stock.picking']
        
        _logger.info("validate_delivery: using move.quantity_done path (module %s)", __name__)

        # Trova il picking per ID o nome
        picking = None
        if picking_id:
            picking = StockPicking.browse(picking_id)
        elif picking_name:
            picking = StockPicking.search([('name', '=', picking_name)], limit=1)
        else:
            return {"error": "Specificare picking_id o picking_name"}
        
        if not picking.exists():
            return {"error": f"Delivery '{picking_name or picking_id}' non trovato"}
        
        if picking.state == 'done':
            return {"error": "L'ordine è già stato evaso"}
        
        try:
            # 1) Prenota quanto disponibile
            picking.action_assign()

            # 2) Verifica che ogni move sia completamente prenotato
            not_fully_reserved = []
            for move in picking.move_ids:
                
                qty = getattr(move, 'quantity', None)  
                demand = getattr(move, 'product_uom_qty', 0.0)
                if qty is None:
                    # fallback conservativo: somma le quantità riservate dalle move_line
                    qty = sum(ml.quantity for ml in move.move_line_ids if hasattr(ml, 'quantity'))
                if (qty or 0.0) < (demand or 0.0):
                    not_fully_reserved.append({
                        "move": move.id,
                        "product": move.product_id.display_name,
                        "reserved": qty or 0.0,
                        "demand": demand or 0.0,
                    })

            if not_fully_reserved:
                # Invece di errore secco, chiedi DECISIONE all'utente via chat
                return {
                    "requires_decision": True,
                    "picking_id": picking.id,
                    "picking_name": picking.name,
                    "message": (
                        "Quantità non completamente prenotate: come vuoi procedere?\n"
                        "1) Evadi ORA e CREA Backorder\n"
                        "2) Evadi ORA SENZA Backorder (scarta residuo)\n"
                        "3) Trasferimento immediato (imposta done = demand e valida tutto)"
                    ),
                    "details": not_fully_reserved
                }
            
            # Valida il picking
            picking.button_validate()
            
            return {
                "success": True,
                "message": f"Ordine {picking.name} evaso con successo",
                "picking_id": picking.id,
                "picking_name": picking.name,
            }
        except Exception as e:
            return {"error": f"Errore durante l'evasione: {str(e)}"}
    
    @api.model
    def process_delivery_decision(self, picking_name=None, picking_id=None, decision=None):
        """
        Applica la scelta utente dopo un tentativo di validazione (Odoo 18 compatibile).
        decision ∈ {'backorder', 'no_backorder', 'immediate'}
        
        LOGICA ODOO 18:
        - 'immediate': Forza consegna totale impostando qty_done = demand per tutti i movimenti
        - 'backorder': Consegna parziale con backorder (se disponibilità = 0, lascia in attesa)
        - 'no_backorder': Consegna parziale senza backorder (se disponibilità = 0, annulla picking)
        
        Args:
            picking_name (str): Nome del delivery (es. "WH/OUT/00035")
            picking_id (int): ID del picking (alternativa a picking_name)
            decision (str): 'backorder' | 'no_backorder' | 'immediate'
        
        Returns:
            Dict con successo/errore e info backorder creati
        """
        StockPicking = self.env['stock.picking']
        StockMoveLine = self.env['stock.move.line']

        # 1) Carica il picking
        if picking_id:
            picking = StockPicking.browse(picking_id)
        elif picking_name:
            picking = StockPicking.search([('name', '=', picking_name)], limit=1)
        else:
            return {"error": "Specificare picking_id o picking_name"}

        if not picking.exists():
            return {"error": f"Delivery '{picking_name or picking_id}' non trovato"}

        if picking.state == 'done':
            return {"error": f"Delivery {picking.name} già validato (stato: done)"}
        
        if not decision:
            return {"error": "Parametro 'decision' obbligatorio: backorder | no_backorder | immediate"}

        try:
            # 2) Prepara il picking (assicura che sia assigned)
            if picking.state not in ('assigned', 'confirmed'):
                picking.action_assign()
            
            # 3) Calcola disponibilità totale riservata
            reserved_total = 0.0
            for move in picking.move_ids:
                if move.state in ('cancel', 'done'):
                    continue
                # Somma le quantità dalle move_line (quelle con quantity > 0 sono riservate)
                reserved_total += sum(ml.quantity for ml in move.move_line_ids if hasattr(ml, 'quantity'))
            
            _logger.info(f"process_delivery_decision: {picking.name}, decision={decision}, reserved_total={reserved_total}")
            
            # ========== OPZIONE 3: TRASFERIMENTO IMMEDIATO ==========
            if decision == 'immediate':
                _logger.info(f"Immediate transfer for {picking.name}: forcing qty_done = demand for all moves")
                
                # Imposta qty_done = demand per TUTTI i movimenti (anche se non riservati)
                for move in picking.move_ids:
                    if move.state in ('cancel', 'done'):
                        continue
                    
                    demand = move.product_uom_qty
                    
                    # Se esistono move_line, aggiorna qty_done
                    if move.move_line_ids:
                        # Distribuisci la domanda sulle move_line esistenti
                        # (Per semplicità, impostiamo la prima move_line con tutta la quantità)
                        for ml in move.move_line_ids:
                            if hasattr(ml, 'quantity'):
                                ml.quantity = demand  # Odoo 18: campo 'quantity'
                            elif hasattr(ml, 'qty_done'):
                                ml.qty_done = demand  # Fallback v17
                            else:
                                ml.write({'quantity': demand})
                            break  # Prima riga prende tutta la quantità
                    else:
                        # Crea nuova move_line con qty_done = demand
                        StockMoveLine.create({
                            'move_id': move.id,
                            'product_id': move.product_id.id,
                            'product_uom_id': move.product_uom.id,
                            'location_id': move.location_id.id,
                            'location_dest_id': move.location_dest_id.id,
                            'quantity': demand,  # Odoo 18
                            'picking_id': picking.id,
                        })
                
                # Valida senza popup backorder
                picking.with_context(skip_backorder=True, skip_immediate=True).button_validate()
                
                
                return {
                    "success": True,
                    "picking_id": picking.id,
                    "picking_name": picking.name,
                    "state": picking.state,
                    "created_backorders": [],
                    "message": f"✅ Evasione completata con Trasferimento immediato – Delivery: {picking.name} - Stato: {picking.state}",
                }
            
            # ========== OPZIONE 1: BACKORDER (consegna parziale + backorder) ==========
            elif decision == 'backorder':
                # Caso A: Nessuna quantità disponibile → Lascia tutto in attesa (backorder totale implicito)
                if reserved_total <= 0.0:
                    _logger.info(f"Backorder decision but no reserved qty for {picking.name}: leaving in pending state")
                    return {
                        "success": True,
                        "picking_id": picking.id,
                        "picking_name": picking.name,
                        "state": picking.state,
                        "created_backorders": [],
                        "message": (
                            f"⏳ Nessuna quantità disponibile ora per {picking.name}. "
                            "Tutti i prodotti rimangono in attesa (backorder totale). "
                            "La consegna sarà evasa quando la merce sarà disponibile."
                        ),
                        "note": "Il picking resta nello stato originario (non validato) in attesa di disponibilità."
                    }
                
                # Caso B: Disponibilità parziale → Imposta qty_done = reserved e usa wizard backorder
                _logger.info(f"Backorder decision with reserved qty for {picking.name}: partial delivery + backorder")
                
                # Imposta qty_done = reserved usando il campo corretto di Odoo 18
                for move in picking.move_ids:
                    if move.state in ('cancel', 'done'):
                        continue
                    # Somma le quantità riservate dalle move_line
                    reserved_qty = sum(ml.quantity for ml in move.move_line_ids if hasattr(ml, 'quantity'))
                    move.quantity_done = reserved_qty
                
                # Usa wizard backorder per creare backorder automatico
                wiz = self.env['stock.backorder.confirmation'].with_context(
                    button_validate_picking_ids=[picking.id],
                    default_pick_ids=[(6, 0, [picking.id])],
                    default_show_transfers=False,
                ).create({})
                wiz.process()  # Crea backorder e valida parziale
                
                
                created_backorders = self.env['stock.picking'].search([('backorder_id', '=', picking.id)])
                
                return {
                    "success": True,
                    "picking_id": picking.id,
                    "picking_name": picking.name,
                    "state": picking.state,
                    "created_backorders": [{"id": b.id, "name": b.name, "state": b.state} for b in created_backorders],
                    "message": (
                        f"✅ Evasione parziale con Backorder creato – Delivery: {picking.name} - Stato: {picking.state}\n"
                        f"Backorder creati: {', '.join(b.name for b in created_backorders)}"
                    ) if created_backorders else f"✅ Consegna completata: {picking.name}",
                }
            
            # ========== OPZIONE 2: NO BACKORDER (consegna parziale SENZA backorder) ==========
            elif decision == 'no_backorder':
                # Caso A: Nessuna quantità disponibile → Annulla picking
                if reserved_total <= 0.0:
                    _logger.info(f"No backorder decision but no reserved qty for {picking.name}: cancelling picking")
                    picking.action_cancel()
                    
                    return {
                        "success": True,
                        "picking_id": picking.id,
                        "picking_name": picking.name,
                        "state": picking.state,
                        "created_backorders": [],
                        "message": (
                            f"❌ Trasferimento annullato: {picking.name}\n"
                            "Nessun prodotto disponibile, ordine di consegna cancellato senza backorder."
                        ),
                        "note": "Il picking è stato annullato (stato: cancel). Nessuna spedizione effettuata."
                    }
                
                # Caso B: Disponibilità parziale → Imposta qty_done = reserved e usa wizard no_backorder
                _logger.info(f"No backorder decision with reserved qty for {picking.name}: partial delivery without backorder")
                
                # Imposta qty_done = reserved usando il campo corretto di Odoo 18
                for move in picking.move_ids:
                    if move.state in ('cancel', 'done'):
                        continue
                    # Somma le quantità riservate dalle move_line
                    reserved_qty = sum(ml.quantity for ml in move.move_line_ids if hasattr(ml, 'quantity'))
                    move.quantity_done = reserved_qty
                
                # Usa wizard backorder per annullare residuo
                wiz = self.env['stock.backorder.confirmation'].with_context(
                    button_validate_picking_ids=[picking.id],
                    default_pick_ids=[(6, 0, [picking.id])],
                    default_show_transfers=False,
                ).create({})
                wiz.process_cancel_backorder()  # Valida parziale e scarta residuo
                
               
                return {
                    "success": True,
                    "picking_id": picking.id,
                    "picking_name": picking.name,
                    "state": picking.state,
                    "created_backorders": [],
                    "message": (
                        f"✅ Evasione parziale SENZA Backorder (residuo annullato) – "
                        f"Delivery: {picking.name} - Stato: {picking.state}"
                    ),
                    "note": "Quantità non disponibili sono state scartate (non verranno consegnate)."
                }
            
            else:
                return {"error": f"Decisione non riconosciuta: {decision}. Valori ammessi: backorder | no_backorder | immediate"}
        
        except Exception as e:
            _logger.exception(f"Errore in process_delivery_decision per {picking.name}")
            return {"error": f"Errore durante l'elaborazione della decisione: {str(e)}"}
    
    @api.model
    def create_sales_order(self, partner_name, order_lines, confirm=True, scheduled_date=None):
        """
        Crea un Sales Order e lo conferma per generare automaticamente il Delivery.
        Questo è il flusso STANDARD per "ordini da evadere" (Sales-driven).
        
        Args:
            partner_name: Nome del cliente
            order_lines: [{"product_id": 1, "quantity": 5, "price_unit": 100.0}, ...]
            confirm: Se True, conferma l'ordine (genera automaticamente il picking)
            scheduled_date: Data pianificata consegna (formato ISO: "2025-10-21" o datetime)
        
        Returns:
            Dict con info su Sales Order e Delivery generato
        """
        Partner = self.env['res.partner']
        Product = self.env['product.product']
        SaleOrder = self.env['sale.order']
        SaleOrderLine = self.env['sale.order.line']
        
        # Trova il cliente
        partner = Partner.search([('name', 'ilike', partner_name)], limit=1)
        if not partner:
            return {"error": f"Cliente '{partner_name}' non trovato"}
        
        # Crea il Sales Order
        order_vals = {
            'partner_id': partner.id,
            'partner_invoice_id': partner.id,
            'partner_shipping_id': partner.id,
        }
        
        # Gestisci commitment_date (data consegna promessa)
        if scheduled_date:
            order_vals['commitment_date'] = scheduled_date
        
        sale_order = SaleOrder.create(order_vals)
        
        # Aggiungi le righe ordine
        created_lines = []
        for line in order_lines:
            product = Product.browse(line['product_id'])
            if not product.exists():
                continue
            
            # Usa il prezzo dal parametro o quello di listino
            price_unit = line.get('price_unit', product.list_price)
            
            order_line = SaleOrderLine.create({
                'order_id': sale_order.id,
                'product_id': product.id,
                'product_uom_qty': line['quantity'],
                'product_uom': product.uom_id.id,
                'price_unit': price_unit,
                'name': product.name,
            })
            created_lines.append({
                'product': product.name,
                'quantity': line['quantity'],
                'price_unit': price_unit,
                'subtotal': order_line.price_subtotal
            })
        
        result = {
            "success": True,
            "sale_order_id": sale_order.id,
            "sale_order_name": sale_order.name,
            "partner": partner.name,
            "state": sale_order.state,
            "amount_total": sale_order.amount_total,
            "order_lines": created_lines,
        }
        
        # Conferma l'ordine (genera automaticamente i picking secondo le regole di magazzino)
        if confirm:
            try:
                sale_order.action_confirm()
                result['state'] = sale_order.state
                result['message'] = f"Ordine di vendita {sale_order.name} confermato"
                
                # Recupera i delivery generati automaticamente
                if sale_order.picking_ids:
                    # Se c'è una scheduled_date, applicala ai picking
                    if scheduled_date:
                        for picking in sale_order.picking_ids:
                            picking.scheduled_date = scheduled_date
                    
                    pickings_info = [{
                        'picking_id': p.id,
                        'picking_name': p.name,
                        'picking_state': p.state,
                        'scheduled_date': p.scheduled_date.strftime("%Y-%m-%d %H:%M") if p.scheduled_date else None,
                    } for p in sale_order.picking_ids]
                    result['pickings'] = pickings_info
                    result['message'] += f" - Generati {len(pickings_info)} picking automaticamente"
                    
            except Exception as e:
                result['warning'] = f"Ordine creato ma errore nella conferma: {str(e)}"
        
        return result
    
    @api.model
    def create_delivery_order(self, partner_name, product_items):
        """
        Crea un Transfer (stock.picking) diretto SENZA Sales Order.
        USARE SOLO per casi eccezionali: omaggi, sostituzioni, campionature, movimenti spot.
        
        Per ordini commerciali normali, usare create_sales_order() che segue il flusso standard.
        
        Args:
            partner_name: Nome destinatario
            product_items: [{"product_id": 1, "quantity": 5}, ...]
        """
        Partner = self.env['res.partner']
        Product = self.env['product.product']
        StockPicking = self.env['stock.picking']
        StockMove = self.env['stock.move']
        
        # Trova il partner
        partner = Partner.search([('name', 'ilike', partner_name)], limit=1)
        if not partner:
            return {"error": f"Cliente '{partner_name}' non trovato"}
        
        # Trova il tipo di picking per le consegne
        picking_type = self.env['stock.picking.type'].search([
            ('code', '=', 'outgoing')
        ], limit=1)
        
        if not picking_type:
            return {"error": "Tipo di operazione 'Consegna' non trovato"}
        
        # Crea il picking
        picking = StockPicking.create({
            'partner_id': partner.id,
            'picking_type_id': picking_type.id,
            'location_id': picking_type.default_location_src_id.id,
            'location_dest_id': partner.property_stock_customer.id,
        })
        
        # Aggiungi i movimenti di stock
        for item in product_items:
            product = Product.browse(item['product_id'])
            if not product.exists():
                continue
                
            StockMove.create({
                'name': product.name,
                'product_id': product.id,
                'product_uom_qty': item['quantity'],
                'product_uom': product.uom_id.id,
                'picking_id': picking.id,
                'location_id': picking_type.default_location_src_id.id,
                'location_dest_id': partner.property_stock_customer.id,
            })
        
        return {
            "success": True,
            "message": f"Transfer diretto {picking.name} creato (senza Sales Order)",
            "picking_id": picking.id,
            "picking_name": picking.name,
            "warning": "Questo è un movimento inventory-driven: nessuna tracciabilità commerciale (preventivo/fattura)"
        }

    @api.model
    def search_partners(self, search_term=None, limit=5, is_customer=True):
        """
        Cerca partner (clienti) per nome/email/telefono.
        Ritorna una lista di suggerimenti da usare per selezionare il cliente corretto.

        Args:
            search_term (str): frammento da cercare su name/email/phone
            limit (int): massimo risultati
            is_customer (bool): se True filtra su customer_rank > 0

        Returns:
            List[Dict]: [{id, name, email, phone}]
        """
        Partner = self.env['res.partner']
        domain = []
        if search_term:
            # Cerca su name OR email OR phone
            domain += ['|', '|',
                       ('name', 'ilike', search_term),
                       ('email', 'ilike', search_term),
                       ('phone', 'ilike', search_term)]
        if is_customer:
            domain.append(('customer_rank', '>', 0))

        partners = Partner.search(domain, limit=limit)
        return [{
            'id': p.id,
            'name': p.name,
            'email': p.email or '',
            'phone': p.phone or ''
        } for p in partners]

    @api.model
    def create_partner(self, name, email=None, phone=None, mobile=None, street=None,
                       city=None, zip=None, country_code=None, vat=None,
                       company_name=None, is_company=False):
        """
        Crea un nuovo partner cliente (res.partner) con customer_rank=1.
        Se esiste già un partner con lo stesso nome (match case-insensitive), ritorna quello esistente.

        Args:
            name (str): Nome completo del partner (obbligatorio)
            email (str, opzionale)
            phone (str, opzionale)
            mobile (str, opzionale)
            street, city, zip (opzionali)
            country_code (str, opzionale): codice ISO a 2 lettere (es. IT, FR)
            vat (str, opzionale): Partita IVA
            company_name (str, opzionale): Azienda a cui collegare il contatto
            is_company (bool, opzionale): Se True crea un'azienda

        Returns:
            Dict con info del partner creato o esistente
        """
        Partner = self.env['res.partner']
        Country = self.env['res.country']

        if not name or not name.strip():
            return {"error": "Parametro 'name' obbligatorio per creare un partner"}

        # Se esiste già un partner con lo stesso nome (case-insensitive), restituiscilo
        existing = Partner.search([('name', '=ilike', name.strip())], limit=1)
        if existing:
            return {
                "success": True,
                "message": f"Partner già esistente: {existing.name}",
                "partner_id": existing.id,
                "partner_name": existing.name,
                "existing": True,
            }

        vals = {
            'name': name.strip(),
            'email': email or False,
            'phone': phone or False,
            'mobile': mobile or False,
            'street': street or False,
            'city': city or False,
            'zip': zip or False,
            'vat': vat or False,
            'is_company': bool(is_company),
            'customer_rank': 1,
        }

        if country_code:
            country = Country.search([('code', '=', country_code.upper())], limit=1)
            if country:
                vals['country_id'] = country.id

        # Collega a company parent se fornita
        if company_name and not vals.get('is_company'):
            company = Partner.search([('name', '=ilike', company_name)], limit=1)
            if not company:
                company = Partner.create({
                    'name': company_name,
                    'is_company': True,
                    'customer_rank': 1,
                })
            vals['parent_id'] = company.id

        partner = Partner.create(vals)
        return {
            "success": True,
            "message": f"Partner creato: {partner.name}",
            "partner_id": partner.id,
            "partner_name": partner.name,
            "existing": False,
        }
    
    @api.model
    def update_sales_order(self, order_name=None, order_id=None, order_lines_updates=None, scheduled_date=None):
        """
        Aggiorna un Sales Order esistente modificando le quantità o aggiungendo/rimuovendo righe.
        Funziona SOLO su ordini in stato 'draft' o 'sent'.
        
        Args:
            order_name (str): Nome dell'ordine (es. "SO042")
            order_id (int): ID dell'ordine (alternativa a order_name)
            order_lines_updates (list): [
                {"line_id": 123, "quantity": 10},  # Modifica riga esistente
                {"product_id": 25, "quantity": 5},  # Aggiungi nuova riga
                {"line_id": 124, "delete": True},   # Elimina riga
            ]
            scheduled_date (str/datetime): Data consegna pianificata (formato ISO: "2025-10-21" o datetime)
        
        Returns:
            Dict con info aggiornamento
        """
        SaleOrder = self.env['sale.order']
        SaleOrderLine = self.env['sale.order.line']
        Product = self.env['product.product']
        
        # Trova l'ordine
        if order_id:
            order = SaleOrder.browse(order_id)
        elif order_name:
            order = SaleOrder.search([('name', '=', order_name)], limit=1)
        else:
            return {"error": "Specificare order_name o order_id"}
        
        if not order.exists():
            return {"error": f"Ordine '{order_name or order_id}' non trovato"}
        
        # Controlla se l'ordine è modificabile
        if order.state not in ('draft', 'sent'):
            return {
                "error": f"Ordine {order.name} non modificabile (stato: {order.state}). "
                         "Solo ordini in bozza o inviati possono essere modificati. "
                         "Se l'ordine è confermato, devi annullarlo prima."
            }
        
        if not order_lines_updates and not scheduled_date:
            return {"error": "Nessuna modifica specificata in order_lines_updates o scheduled_date"}
        
        # Gestisci scheduled_date se fornita
        if scheduled_date:
            if isinstance(scheduled_date, str):
                from datetime import datetime
                try:
                    # Prova formati: "2025-10-21" o "2025-10-21 14:00:00"
                    if ' ' in scheduled_date:
                        scheduled_date = datetime.strptime(scheduled_date, "%Y-%m-%d %H:%M:%S")
                    else:
                        scheduled_date = datetime.strptime(scheduled_date, "%Y-%m-%d")
                except ValueError as e:
                    return {"error": f"Formato data non valido: {scheduled_date}. Usa 'YYYY-MM-DD' o 'YYYY-MM-DD HH:MM:SS'"}
            
            # Aggiorna commitment_date sull'ordine (data promessa al cliente)
            order.write({'commitment_date': scheduled_date})
            
            # Aggiorna anche scheduled_date sui picking collegati (se l'ordine è confermato)
            for picking in order.picking_ids:
                picking.write({'scheduled_date': scheduled_date})
        
        updated_lines = []
        added_lines = []
        deleted_lines = []
        
        for update in order_lines_updates:
            # Caso 1: Elimina riga esistente
            if update.get('delete') and update.get('line_id'):
                line = SaleOrderLine.browse(update['line_id'])
                if line.exists() and line.order_id.id == order.id:
                    deleted_lines.append(line.product_id.name)
                    line.unlink()
                continue
            
            # Caso 2: Modifica quantità riga esistente
            if update.get('line_id'):
                line = SaleOrderLine.browse(update['line_id'])
                if line.exists() and line.order_id.id == order.id:
                    old_qty = line.product_uom_qty
                    line.write({'product_uom_qty': update['quantity']})
                    updated_lines.append({
                        'product': line.product_id.name,
                        'old_quantity': old_qty,
                        'new_quantity': update['quantity']
                    })
            
            # Caso 3: Aggiungi nuova riga
            elif update.get('product_id'):
                product = Product.browse(update['product_id'])
                if not product.exists():
                    continue
                
                price_unit = update.get('price_unit', product.list_price)
                
                new_line = SaleOrderLine.create({
                    'order_id': order.id,
                    'product_id': product.id,
                    'product_uom_qty': update['quantity'],
                    'product_uom': product.uom_id.id,
                    'price_unit': price_unit,
                    'name': product.name,
                })
                added_lines.append({
                    'product': product.name,
                    'quantity': update['quantity'],
                    'price_unit': price_unit
                })
        
        result = {
            "success": True,
            "message": f"Ordine {order.name} aggiornato",
            "order_id": order.id,
            "order_name": order.name,
            "state": order.state,
            "amount_total": order.amount_total,
            "updated_lines": updated_lines,
            "added_lines": added_lines,
            "deleted_lines": deleted_lines,
        }
        
        # Aggiungi scheduled_date al risultato se aggiornato
        if scheduled_date:
            result["scheduled_date"] = order.commitment_date.strftime("%Y-%m-%d %H:%M") if order.commitment_date else None
            result["message"] += f" - Data consegna aggiornata: {result['scheduled_date']}"
        
        return result
    
    @api.model
    def update_delivery(self, picking_name=None, picking_id=None, move_updates=None):
        """
        Modifica le quantità su un Delivery/Transfer esistente NON ancora validato.
        Funziona SOLO su picking in stato 'draft', 'waiting', 'confirmed', 'assigned'.
        
        Args:
            picking_name (str): Nome del delivery (es. "WH/OUT/00025")
            picking_id (int): ID del picking (alternativa a picking_name)
            move_updates (list): [
                {"move_id": 123, "quantity": 10},  # Modifica movimento esistente
                {"product_id": 25, "quantity": 5},  # Aggiungi nuovo movimento
                {"move_id": 124, "delete": True},   # Elimina movimento
            ]
        
        Returns:
            Dict con info aggiornamento
        """
        StockPicking = self.env['stock.picking']
        StockMove = self.env['stock.move']
        Product = self.env['product.product']
        
        # Trova il picking
        if picking_id:
            picking = StockPicking.browse(picking_id)
        elif picking_name:
            picking = StockPicking.search([('name', '=', picking_name)], limit=1)
        else:
            return {"error": "Specificare picking_name o picking_id"}
        
        if not picking.exists():
            return {"error": f"Delivery '{picking_name or picking_id}' non trovato"}
        
        # Controlla se il picking è modificabile
        if picking.state == 'done':
            return {
                "error": f"Delivery {picking.name} già validato (stato: done). "
                         "Non è possibile modificare un delivery già evaso."
            }
        
        if picking.state == 'cancel':
            return {"error": f"Delivery {picking.name} annullato, non modificabile"}
        
        if not move_updates:
            return {"error": "Nessuna modifica specificata in move_updates"}
        
        updated_moves = []
        added_moves = []
        deleted_moves = []
        
        for update in move_updates:
            # Caso 1: Elimina movimento esistente
            if update.get('delete') and update.get('move_id'):
                move = StockMove.browse(update['move_id'])
                if move.exists() and move.picking_id.id == picking.id:
                    deleted_moves.append(move.product_id.name)
                    move._action_cancel()
                    move.unlink()
                continue
            
            # Caso 2: Modifica quantità movimento esistente
            if update.get('move_id'):
                move = StockMove.browse(update['move_id'])
                if move.exists() and move.picking_id.id == picking.id:
                    old_qty = move.product_uom_qty
                    move.write({'product_uom_qty': update['quantity']})
                    updated_moves.append({
                        'product': move.product_id.name,
                        'old_quantity': old_qty,
                        'new_quantity': update['quantity']
                    })
            
            # Caso 3: Aggiungi nuovo movimento
            elif update.get('product_id'):
                product = Product.browse(update['product_id'])
                if not product.exists():
                    continue
                
                new_move = StockMove.create({
                    'name': product.name,
                    'product_id': product.id,
                    'product_uom_qty': update['quantity'],
                    'product_uom': product.uom_id.id,
                    'picking_id': picking.id,
                    'location_id': picking.location_id.id,
                    'location_dest_id': picking.location_dest_id.id,
                })
                added_moves.append({
                    'product': product.name,
                    'quantity': update['quantity']
                })
        
        # Ricalcola disponibilità se necessario
        if picking.state == 'assigned':
            picking.action_assign()
        
        return {
            "success": True,
            "message": f"Delivery {picking.name} aggiornato",
            "picking_id": picking.id,
            "picking_name": picking.name,
            "state": picking.state,
            "updated_moves": updated_moves,
            "added_moves": added_moves,
            "deleted_moves": deleted_moves,
        }
    
    
    # SALES MANAGEMENT - Panoramica Vendite
    
    
    @api.model
    def get_sales_overview(self, period='month', state=None, limit=100):
        """
        Ottiene panoramica ordini di vendita con statistiche.
        
        Args:
            period: 'day', 'week', 'month', 'year', 'all' (default: 'month')
            state: Filtra per stato ('draft', 'sent', 'sale', 'done', 'cancel'). Se None mostra tutti
            limit: Massimo ordini da mostrare (default 100)
        
        Returns:
            {
                "period": "month",
                "total_orders": 15,
                "total_revenue": 45000.00,
                "avg_order_value": 3000.00,
                "orders_by_state": {"draft": 3, "sale": 10, "done": 2},
                "orders": [
                    {
                        "id": 34,
                        "name": "S00034",
                        "partner": "Gemini Furniture",
                        "date_order": "2025-10-17",
                        "state": "sale",
                        "amount_total": 3200.00,
                        "invoice_status": "to invoice"
                    }
                ]
            }
        """
        SaleOrder = self.env['sale.order']
        
        # Costruisci dominio temporale
        domain = []
        
        if period != 'all':
            from datetime import datetime, timedelta
            today = datetime.now()
            
            if period == 'day':
                start_date = today.replace(hour=0, minute=0, second=0, microsecond=0)
            elif period == 'week':
                start_date = today - timedelta(days=today.weekday())
            elif period == 'month':
                start_date = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            elif period == 'year':
                start_date = today.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            else:
                start_date = None
            
            if start_date:
                domain.append(('date_order', '>=', start_date))
        
        # Filtra per stato
        if state:
            domain.append(('state', '=', state))
        
        # Cerca ordini
        orders = SaleOrder.search(domain, limit=limit, order='date_order DESC')
        
        # Statistiche
        total_revenue = sum(o.amount_total for o in orders)
        avg_order_value = total_revenue / len(orders) if orders else 0.0
        
        # Raggruppa per stato
        orders_by_state = {}
        for order in orders:
            state_key = order.state
            orders_by_state[state_key] = orders_by_state.get(state_key, 0) + 1
        
        # Prepara lista ordini
        orders_data = []
        for order in orders:
            orders_data.append({
                "id": order.id,
                "name": order.name,
                "partner_id": order.partner_id.id,
                "partner": order.partner_id.name,
                "date_order": order.date_order.strftime("%Y-%m-%d") if order.date_order else None,
                "state": order.state,
                "state_display": dict(order._fields['state'].selection).get(order.state),
                "amount_untaxed": order.amount_untaxed,
                "amount_tax": order.amount_tax,
                "amount_total": order.amount_total,
                "invoice_status": order.invoice_status,
                "delivery_status": order.delivery_status if hasattr(order, 'delivery_status') else None,
                "user_id": order.user_id.name if order.user_id else None,
            })
        
        return {
            "period": period,
            "total_orders": len(orders),
            "total_revenue": total_revenue,
            "avg_order_value": avg_order_value,
            "orders_by_state": orders_by_state,
            "orders": orders_data
        }
    
    @api.model
    def get_sales_order_details(self, order_name=None, order_id=None):
        """
        Ottiene dettagli completi di un ordine di vendita, incluse righe prodotto e delivery collegati.
        
        Args:
            order_name: Nome ordine (es. "S00034")
            order_id: ID ordine (alternativa a order_name)
        
        Returns:
            {
                "order_id": 34,
                "order_name": "S00034",
                "partner": "Gemini Furniture",
                "state": "sale",
                "amount_total": 3200.00,
                "order_lines": [
                    {
                        "product": "Armadietto grande",
                        "quantity": 10,
                        "price_unit": 320.00,
                        "subtotal": 3200.00
                    }
                ],
                "pickings": [
                    {
                        "picking_name": "WH/OUT/00022",
                        "state": "assigned"
                    }
                ]
            }
        """
        SaleOrder = self.env['sale.order']
        
        # Trova l'ordine
        if order_id:
            order = SaleOrder.browse(order_id)
        elif order_name:
            order = SaleOrder.search([('name', '=', order_name)], limit=1)
        else:
            return {"error": "Specificare order_name o order_id"}
        
        if not order.exists():
            return {"error": f"Ordine '{order_name or order_id}' non trovato"}
        
        
        
        # Righe ordine
        order_lines = []
        for line in order.order_line:
            order_lines.append({
                "line_id": line.id,
                "product_id": line.product_id.id,
                "product": line.product_id.name,
                "product_code": line.product_id.default_code or "",
                "quantity": line.product_uom_qty,
                "qty_delivered": line.qty_delivered,
                "qty_invoiced": line.qty_invoiced,
                "price_unit": line.price_unit,
                "discount": line.discount,
                "tax": line.tax_id.mapped('name') if line.tax_id else [],
                "subtotal": line.price_subtotal,
                "total": line.price_total,
            })
        
        # Delivery collegati
        pickings = []
        for picking in order.picking_ids:
            pickings.append({
                "picking_id": picking.id,
                "picking_name": picking.name,
                "picking_type": picking.picking_type_id.name,
                "state": picking.state,
                "state_display": dict(picking._fields['state'].selection).get(picking.state),
                "scheduled_date": picking.scheduled_date.strftime("%Y-%m-%d %H:%M") if picking.scheduled_date else None,
            })
        
        # Fatture collegate
        invoices = []
        for invoice in order.invoice_ids:
            invoices.append({
                "invoice_id": invoice.id,
                "invoice_name": invoice.name,
                "state": invoice.state,
                "amount_total": invoice.amount_total,
                "payment_state": invoice.payment_state if hasattr(invoice, 'payment_state') else None,
            })
        
        # --- Delivery status computato dai quantitativi ---
        ordered_qty = sum(line.product_uom_qty for line in order.order_line)
        delivered_qty = sum(line.qty_delivered for line in order.order_line)

        if not ordered_qty:
            delivery_status_computed = 'nothing_to_deliver'
        elif delivered_qty == 0:
            delivery_status_computed = 'not_delivered'
        elif delivered_qty < ordered_qty:
            delivery_status_computed = 'partially_delivered'
        else:
            delivery_status_computed = 'fully_delivered'
        
        return {
            "order_id": order.id,
            "order_name": order.name,
            "partner_id": order.partner_id.id,
            "partner": order.partner_id.name,
            "partner_email": order.partner_id.email or "",
            "partner_phone": order.partner_id.phone or "",
            "date_order": order.date_order.strftime("%Y-%m-%d %H:%M") if order.date_order else None,
            "validity_date": order.validity_date.strftime("%Y-%m-%d") if order.validity_date else None,
            "user_id": order.user_id.name if order.user_id else None,
            "state": order.state,
            "state_display": dict(order._fields['state'].selection).get(order.state),
            "amount_untaxed": order.amount_untaxed,
            "amount_tax": order.amount_tax,
            "amount_total": order.amount_total,
            "invoice_status": order.invoice_status,
            "delivery_status": order.delivery_status if hasattr(order, 'delivery_status') else None,
            "delivery_status_computed": delivery_status_computed,
            "delivery_progress": {"ordered": ordered_qty, "delivered": delivered_qty},
            "order_lines": order_lines,
            "order_lines_count": len(order_lines),
            "pickings": pickings,
            "pickings_count": len(pickings),
            "invoices": invoices,
            "invoices_count": len(invoices),
            "note": order.note or "",
        }
    
    @api.model
    def get_top_customers(self, period='month', limit=10):
        """
        Ottiene classifica top clienti per fatturato nel periodo.
        
        Args:
            period: 'month', 'quarter', 'year', 'all' (default: 'month')
            limit: Numero clienti da mostrare (default 10)
        
        Returns:
            {
                "period": "month",
                "top_customers": [
                    {
                        "partner_id": 7,
                        "partner": "Gemini Furniture",
                        "total_orders": 5,
                        "total_revenue": 15000.00,
                        "avg_order_value": 3000.00
                    }
                ]
            }
        """
        SaleOrder = self.env['sale.order']
        
        # Costruisci dominio temporale
        domain = [('state', 'in', ['sale', 'done'])]  # Solo ordini confermati
        
        if period != 'all':
            from datetime import datetime, timedelta
            today = datetime.now()
            
            if period == 'month':
                start_date = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            elif period == 'quarter':
                quarter_month = ((today.month - 1) // 3) * 3 + 1
                start_date = today.replace(month=quarter_month, day=1, hour=0, minute=0, second=0, microsecond=0)
            elif period == 'year':
                start_date = today.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            else:
                start_date = None
            
            if start_date:
                domain.append(('date_order', '>=', start_date))
        
        # Raggruppa per partner
        orders = SaleOrder.search(domain)
        
        partner_stats = {}
        for order in orders:
            partner_id = order.partner_id.id
            if partner_id not in partner_stats:
                partner_stats[partner_id] = {
                    "partner_id": partner_id,
                    "partner": order.partner_id.name,
                    "partner_email": order.partner_id.email or "",
                    "total_orders": 0,
                    "total_revenue": 0.0,
                }
            
            partner_stats[partner_id]["total_orders"] += 1
            partner_stats[partner_id]["total_revenue"] += order.amount_total
        
        # Calcola media e ordina
        top_customers = []
        for stats in partner_stats.values():
            stats["avg_order_value"] = stats["total_revenue"] / stats["total_orders"] if stats["total_orders"] > 0 else 0.0
            top_customers.append(stats)
        
        # Ordina per fatturato decrescente
        top_customers.sort(key=lambda x: x["total_revenue"], reverse=True)
        
        return {
            "period": period,
            "total_customers": len(top_customers),
            "top_customers": top_customers[:limit]
        }
    
    @api.model
    def get_products_sales_stats(self, period='month', limit=20):
        """
        Ottiene statistiche vendite per prodotto (prodotti più venduti).
        
        Args:
            period: 'month', 'quarter', 'year', 'all' (default: 'month')
            limit: Numero prodotti da mostrare (default 20)
        
        Returns:
            {
                "period": "month",
                "top_products": [
                    {
                        "product_id": 17,
                        "product": "Armadietto grande",
                        "total_qty_sold": 150,
                        "total_revenue": 48000.00,
                        "avg_price": 320.00,
                        "orders_count": 5
                    }
                ]
            }
        """
        SaleOrderLine = self.env['sale.order.line']
        
        # Costruisci dominio temporale
        domain = [('order_id.state', 'in', ['sale', 'done'])]
        
        if period != 'all':
            from datetime import datetime, timedelta
            today = datetime.now()
            
            if period == 'month':
                start_date = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            elif period == 'quarter':
                quarter_month = ((today.month - 1) // 3) * 3 + 1
                start_date = today.replace(month=quarter_month, day=1, hour=0, minute=0, second=0, microsecond=0)
            elif period == 'year':
                start_date = today.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            else:
                start_date = None
            
            if start_date:
                domain.append(('order_id.date_order', '>=', start_date))
        
        # Raggruppa per prodotto
        lines = SaleOrderLine.search(domain)
        
        product_stats = {}
        for line in lines:
            product_id = line.product_id.id
            if product_id not in product_stats:
                product_stats[product_id] = {
                    "product_id": product_id,
                    "product": line.product_id.name,
                    "product_code": line.product_id.default_code or "",
                    "total_qty_sold": 0.0,
                    "total_revenue": 0.0,
                    "orders_count": 0,
                    "order_ids": set(),
                }
            
            product_stats[product_id]["total_qty_sold"] += line.product_uom_qty
            product_stats[product_id]["total_revenue"] += line.price_subtotal
            product_stats[product_id]["order_ids"].add(line.order_id.id)
        
        # Calcola media e ordina
        top_products = []
        for stats in product_stats.values():
            stats["orders_count"] = len(stats["order_ids"])
            stats["avg_price"] = stats["total_revenue"] / stats["total_qty_sold"] if stats["total_qty_sold"] > 0 else 0.0
            del stats["order_ids"]  # Rimuovi set non serializzabile
            top_products.append(stats)
        
        # Ordina per quantità venduta decrescente
        top_products.sort(key=lambda x: x["total_qty_sold"], reverse=True)
        
        return {
            "period": period,
            "total_products": len(top_products),
            "top_products": top_products[:limit]
        }
