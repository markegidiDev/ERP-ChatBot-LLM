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
    def search_products(self, search_term=None, limit=50, product_type=None):
        """
        Cerca prodotti nel catalogo con ricerca FUZZY multi-pattern intelligente.
        
        STRATEGIA DI RICERCA (in ordine):
        1. Match esatto (case-insensitive)
        2. Match tutte le parole chiave (AND con ilike)
        3. Match parziale parole singole (OR con ilike)
        4. Fallback: qualsiasi parola presente

        Args:
            search_term (str): Testo da cercare nel nome prodotto (opzionale)
            limit (int): Massimo risultati (default 50)
            product_type (str): Filtra per tipo prodotto (opzionale)

        Returns:
            List[dict]: Prodotti trovati ordinati per rilevanza
        """
        Product = self.env['product.product']

        # Costruisci dominio base per tipo prodotto
        base_domain = []
        
        if product_type:
            pt = (product_type or '').strip().lower()
            type_map = {
                'service': 'service',
                'servizio': 'service',
                'product': 'product',
                'prodotto': 'product',
                'goods': 'product',
                'storable': 'product',
                'stoccabile': 'product',
                'consu': 'product',        
                'consumable': 'product',
                'consumabile': 'product',
                'combo': 'combo',
            }
            dt = type_map.get(pt)
            if dt:
                if dt == 'product':
                    base_domain.append(('product_tmpl_id.type', 'in', ['product', 'consu']))
                else:
                    base_domain.append(('product_tmpl_id.type', '=', dt))
            else:
                _logger.warning("Tipo prodotto non valido: %s", product_type)

        # Se non c'è termine di ricerca, ritorna tutti con filtro tipo
        if not search_term:
            products = Product.search(base_domain, limit=limit)
            _logger.info("Prodotti trovati: %d (nessun filtro nome)", len(products))
            return self._format_product_results(products)
        
        # RICERCA MULTI-PATTERN
        search_term_clean = search_term.strip()
        
        # PATTERN 1: Match esatto (case-insensitive)
        domain_exact = base_domain + [('name', '=ilike', search_term_clean)]
        products = Product.search(domain_exact, limit=limit)
        
        if products:
            _logger.info("✅ Match ESATTO: '%s' → %d prodotti", search_term_clean, len(products))
            return self._format_product_results(products)
        
        # PATTERN 2: Match tutte le parole (AND)
        # Es: "tavolo pranzo esterno" cerca prodotti con TUTTE e 3 le parole
        words = [w.strip() for w in search_term_clean.split() if len(w.strip()) > 2]
        
        if len(words) > 1:
            domain_all_words = list(base_domain)
            for word in words:
                domain_all_words.append(('name', 'ilike', word))
            
            products = Product.search(domain_all_words, limit=limit)
            
            if products:
                _logger.info("✅ Match TUTTE parole: %s → %d prodotti", words, len(products))
                return self._format_product_results(products)
        
        # PATTERN 3: Match parziale parole singole (OR)
        # Cerca prodotti che contengono ALMENO UNA delle parole chiavee
        if words:
            domain_any_word = list(base_domain)
            word_conditions = []
            for word in words:
                word_conditions.append(('name', 'ilike', word))
            
            # Costruisci OR manuale: ['|', '|', cond1, cond2, cond3]
            if len(word_conditions) > 1:
                or_prefix = ['|'] * (len(word_conditions) - 1)
                domain_any_word = or_prefix + domain_any_word + word_conditions
            else:
                domain_any_word.extend(word_conditions)
            
            products = Product.search(domain_any_word, limit=limit * 2)  # Più risultati per ranking
            
            if products:
                # Ordina per numero di parole matchate
                scored_products = []
                for p in products:
                    name_lower = p.name.lower()
                    score = sum(1 for w in words if w.lower() in name_lower)
                    scored_products.append((score, p))
                
                # Ordina per score decrescente
                scored_products.sort(key=lambda x: x[0], reverse=True)
                best_products = [p for _, p in scored_products[:limit]]
                
                _logger.info("✅ Match PARZIALE parole: %s → %d prodotti (top score: %d)", 
                            words, len(best_products), scored_products[0][0] if scored_products else 0)
                return self._format_product_results(best_products)
        
        # PATTERN 4: Fallback ricerca generica con ilike sul termine completo
        domain_fallback = base_domain + [('name', 'ilike', search_term_clean)]
        products = Product.search(domain_fallback, limit=limit)
        
        _logger.info("⚠️ Fallback ilike: '%s' → %d prodotti", search_term_clean, len(products))
        return self._format_product_results(products)
    
    def _format_product_results(self, products):
        """Helper per formattare risultati prodotti"""
        return [{
            "id": p.id,
            "name": p.name,
            "detailed_type": p.product_tmpl_id.type,
            "qty_available": p.qty_available,
            "list_price": (getattr(p, 'lst_price', False) or p.product_tmpl_id.list_price),
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
        
        # Forza refresh dati dal database
        picking.invalidate_recordset()
        picking.move_ids.invalidate_recordset()
        
        # Ricarica picking dal DB
        picking = StockPicking.browse(picking.id)
        
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
                    # fallback : somma le quantità riservate dalle move_line
                    qty = sum(ml.quantity for ml in move.move_line_ids if hasattr(ml, 'quantity'))
                if (qty or 0.0) < (demand or 0.0):
                    not_fully_reserved.append({
                        "move": move.id,
                        "product": move.product_id.display_name,
                        "reserved": qty or 0.0,
                        "demand": demand or 0.0,
                    })

            if not_fully_reserved:
                #chiede DECISIONE all'utente via chat
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
            # 2) Prepara il picking
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
                # Caso A: Nessuna quantità disponibile → rimane tutto in attesa (niente da spedire ora)
                if reserved_total <= 0.0:
                    _logger.info(f"Backorder decision with no reserved qty for {picking.name}: all products waiting (no delivery now)")
                    return {
                        "success": True,
                        "picking_id": picking.id,
                        "picking_name": picking.name,
                        "state": picking.state,
                        "created_backorders": [],
                        "message": (
                            f"❌ Consegna posticipata: nessuna quantità disponibile per {picking.name}. "
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
                
                # Caso B: Disponibilità parziale Imposta qty_done = reserved e usa wizard no_backorder
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
        # Nota: comportamento aggiornato per evitare duplicati di draft
        Partner = self.env['res.partner']
        Product = self.env['product.product']
        SaleOrder = self.env['sale.order']
        SaleOrderLine = self.env['sale.order.line']

        # Trova il cliente
        partner = Partner.search([('name', 'ilike', partner_name)], limit=1)
        if not partner:
            return {"error": f"Cliente '{partner_name}' non trovato"}

        # Normalizza scheduled_date per confronto
        sd = scheduled_date

        # Costruisci set prodotti in input (product_id -> price_unit)
        input_products = {}
        for line in order_lines:
            pid = int(line.get('product_id'))
            price = float(line.get('price_unit', 0.0)) if line.get('price_unit') is not None else None
            input_products[pid] = price

        # Cerca ordini in bozza per lo stesso partner e (se fornita) stessa scheduled_date
        domain = [('partner_id', '=', partner.id), ('state', '=', 'draft')]
        if sd:
            domain.append(('commitment_date', '=', sd))

        candidates = SaleOrder.search(domain)

        # Trova candidato con stesso insieme di product_id
        matched_order = None
        input_pids = set(input_products.keys())
        for o in candidates:
            o_pids = set(l.product_id.id for l in o.order_line)
            if o_pids == input_pids:
                matched_order = o
                break

        if matched_order:
            # Prepara update payload: imposta le quantità richieste sulle linee esistenti
            updates = []
            for line in matched_order.order_line:
                pid = line.product_id.id
                if pid in input_products:
                    updates.append({'line_id': line.id, 'quantity': next((l['quantity'] for l in order_lines if int(l['product_id']) == pid), line.product_uom_qty)})

            # Aggiungi eventuali prodotti mancanti (non dovrebbe succedere perché pids uguali)
            for l in order_lines:
                if int(l['product_id']) not in [ll.product_id.id for ll in matched_order.order_line]:
                    updates.append({'product_id': int(l['product_id']), 'quantity': l['quantity']})

            # Chiama update_sales_order internamente
            try:
                res = self.update_sales_order(order_id=matched_order.id, order_lines_updates=updates, scheduled_date=sd)
                # Ritorna risultato dell'update con avviso di dedup
                if isinstance(res, dict) and res.get('success'):
                    res['note'] = res.get('note', '') + ' | Usato ordine in bozza esistente (dedup).'
                    return res
                else:
                    return res
            except Exception as e:
                _logger.exception('Errore aggiornando ordine esistente')
                # Fall back al creare nuovo ordine

        # Nessun ordine da aggiornare: crea nuovo ordine
        order_vals = {
            'partner_id': partner.id,
            'partner_invoice_id': partner.id,
            'partner_shipping_id': partner.id,
        }
        if sd:
            order_vals['commitment_date'] = sd

        sale_order = SaleOrder.create(order_vals)

        created_lines = []
        for line in order_lines:
            product = Product.browse(int(line['product_id']))
            if not product.exists():
                continue
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

        # Forza flush e invalidazione cache per avere dati freschi
        self.env.flush_all()
        sale_order.invalidate_recordset()
        sale_order.order_line.invalidate_recordset()
        self.env.cr.commit()
        
        # Ricarica ordine
        sale_order = SaleOrder.browse(sale_order.id)

        result = {
            "success": True,
            "sale_order_id": sale_order.id,
            "sale_order_name": sale_order.name,
            "partner": partner.name,
            "state": sale_order.state,
            "amount_total": sale_order.amount_total,
            "order_lines": created_lines,
            "message": f"Ordine di vendita {sale_order.name} creato (da confermare manualmente)",
        }
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
            vat (str, opzionale)
            company_name (str, opzionale): Nome della società collegata (crea relazione parent)
            is_company (bool): se True, il partner creato è un'azienda
        """
        Partner = self.env['res.partner']
        Country = self.env['res.country']
        
        # Normalizza input
        name = (name or '').strip()
        email = (email or '').strip()
        phone = (phone or '').strip()
        mobile = (mobile or '').strip()
        street = (street or '').strip() if street else None
        city = (city or '').strip() if city else None
        zip = (zip or '').strip() if zip else None
        country_code = (country_code or '').strip().upper() if country_code else None
        vat = (vat or '').strip() if vat else None
        company_name = (company_name or '').strip() if company_name else None
        
        if not name:
            return {"error": "Il campo 'name' è obbligatorio"}
        
        # Se esiste un partner con lo stesso nome (case-insensitive), ritorna quello
        existing = Partner.search([('name', '=ilike', name)], limit=1)
        if existing:
            return {
                "success": True,
                "message": f"Partner esistente trovato: {existing.name}",
                "partner_id": existing.id,
                "partner_name": existing.name,
                "existing": True,
            }
        
        # Prepara valori partner
        vals = {
            'name': name,
            'customer_rank': 1,
            'email': email or None,
            'phone': phone or None,
            'mobile': mobile or None,
            'street': street or None,
            'city': city or None,
            'zip': zip or None,
            'vat': vat or None,
            'is_company': bool(is_company),
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
            if update.get('line_id') and 'quantity' in update:
                line = SaleOrderLine.browse(update['line_id'])
                if line.exists() and line.order_id.id == order.id:
                    try:
                        new_qty = float(update['quantity'])
                    except (TypeError, ValueError):
                        _logger.warning("⚠️ Quantità non valida per line_id %s: %s", update['line_id'], update['quantity'])
                        continue

                    if new_qty <= 0:
                        deleted_lines.append(line.product_id.name)
                        line.unlink()
                    else:
                        old_qty = line.product_uom_qty
                        line.write({'product_uom_qty': new_qty})
                        updated_lines.append({
                            'product': line.product_id.name,
                            'old_quantity': old_qty,
                            'new_quantity': new_qty
                        })
                continue
            
            # Caso 3: Aggiungi nuova riga con product_id
            elif update.get('product_id'):
                qty = float(update.get('quantity', 0) or 0)
                if qty <= 0:
                    _logger.warning("⚠️ Quantità non positiva per product_id %s: %s", update['product_id'], update.get('quantity'))
                    continue
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
            
            # 🆕 Caso 4: Aggiungi nuova riga con product_name (cerca automaticamente)
            elif update.get('product_name'):
                search_term = update['product_name']
                
                # Cerca prodotto per nome (case-insensitive, fuzzy match)
                product = Product.search([
                    ('name', 'ilike', search_term)
                ], limit=1)
                
                if not product:
                    # Fallback: prova normalizzazione con AI (se disponibile)
                    try:
                        channel = self.env['discuss.channel']
                        if hasattr(channel, '_normalize_product_search_term'):
                            normalized = channel._normalize_product_search_term(search_term)
                            product = Product.search([
                                ('name', 'ilike', normalized)
                            ], limit=1)
                    except:
                        pass
                
                if not product:
                    _logger.warning(f"⚠️ Prodotto '{search_term}' non trovato - skip riga")
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
                _logger.info(f"✅ Aggiunta riga: {product.name} x {update['quantity']} (cercato come '{search_term}')")
        
        # FORZA il ricalcolo del totale ordine prima di ritornare
        self.env.flush_all()

        # Invalida TUTTA la cache dell'ordine e delle righe
        order.invalidate_recordset()  # Invalida tutto l'ordine
        order.order_line.invalidate_recordset()  # Invalida tutte le righe

        # COMMIT ESPLICITO per rendere le modifiche visibili
        self.env.cr.commit()
        _logger.info(f"💾 Commit eseguito dopo aggiornamento ordine {order.name}")

        # Ricarica l'ordine dal database
        order = self.env['sale.order'].browse(order.id)
        order_total = order.amount_total
        
        #Costruisci messaggio formattato con newline
        msg_parts = [f"✅ Ordine {order.name} aggiornato"]
        
        if updated_lines:
            msg_parts.append("\nRighe modificate:")
            for u in updated_lines:
                msg_parts.append(f"  • {u['product']}: {u['old_quantity']} → {u['new_quantity']}")
        
        if added_lines:
            msg_parts.append("\nRighe aggiunte:")
            for a in added_lines:
                qty = a.get('quantity')
                msg_parts.append(f"  • {a['product']}: {qty} pz")
        
        if deleted_lines:
            msg_parts.append("\nRighe eliminate:")
            for d in deleted_lines:
                msg_parts.append(f"  • {d}")
        
        result = {
            "success": True,
            "message": "\n".join(msg_parts),  # ← newline garantito
            "order_id": order.id,
            "order_name": order.name,
            "state": order.state,
            "amount_total": order_total,
            "updated_lines": updated_lines,
            "added_lines": added_lines,
            "deleted_lines": deleted_lines,
        }
        
        # Aggiungi scheduled_date al risultato se aggiornato
        if scheduled_date:
            result["scheduled_date"] = (
                order.commitment_date.strftime("%Y-%m-%d %H:%M")
                if order.commitment_date else None
            )
            # Append riga separata per la data
            result["message"] += f"\n\nData consegna aggiornata: {result['scheduled_date']}"
        
        return result
    
    @api.model
    def confirm_sales_order(self, order_name=None, order_id=None):
        """
        Conferma un Sales Order passandolo da draft/sent a sale.
        Genera automaticamente i Delivery Order associati.
        
        Args:
            order_name (str): Nome ordine (es. "S00042")
            order_id (int): ID ordine (alternativa a order_name)
        
        Returns:
            dict: {
                "success": True/False,
                "order_id": int,
                "order_name": str,
                "state": str,
                "state_display": str,
                "message": str,
                "error": str (se presente)
            }
        """
        SaleOrder = self.env['sale.order']
        
        # Trova ordine
        if order_id:
            order = SaleOrder.browse(order_id)
        elif order_name:
            order = SaleOrder.search([('name', '=', order_name)], limit=1)
        else:
            return {"error": "Specificare order_name o order_id"}
        
        if not order.exists():
            return {"error": f"Ordine '{order_name or order_id}' non trovato"}
        
        # Verifica stato
        if order.state not in ('draft', 'sent'):
            state_display = dict(order._fields['state'].selection).get(order.state, order.state)
            return {
                "error": f"Impossibile confermare: ordine già in stato '{state_display}'",
                "order_name": order.name,
                "current_state": order.state,
                "state_display": state_display,
                "solution": "Questo ordine è già confermato o completato"
            }
        
        # Conferma ordine
        try:
            order.action_confirm()
            
            state_display = dict(order._fields['state'].selection).get(order.state, order.state)
            
            return {
                "success": True,
                "order_id": order.id,
                "order_name": order.name,
                "state": order.state,
                "state_display": state_display,
                "message": f"✅ Ordine {order.name} confermato con successo!",
                "partner": order.partner_id.name,
                "total": f"{order.amount_total:.2f} {order.currency_id.symbol}",
                "delivery_count": len(order.picking_ids),
                "deliveries_generated": [p.name for p in order.picking_ids]
            }
        
        except Exception as e:
            _logger.error(f"Errore durante conferma ordine {order.name}: {str(e)}")
            return {
                "error": f"Errore durante la conferma: {str(e)}",
                "order_name": order.name,
                "order_id": order.id
            }
    
    @api.model
    def cancel_sales_order(self, order_name=None, order_id=None):
        """
        Cancella un Sales Order *solo* se è in stato 'draft'.
        """
        SaleOrder = self.env['sale.order']

        # Trova ordine
        if order_id:
            order = SaleOrder.browse(order_id)
        elif order_name:
            order = SaleOrder.search([('name', '=', order_name)], limit=1)
        else:
            return {"error": "Specificare order_name o order_id"}

        if not order.exists():
            return {"error": f"Ordine '{order_name or order_id}' non trovato"}

        # Verifica stato già cancellato
        if order.state == 'cancel':
            return {
                "error": f"Ordine {order.name} è già cancellato",
                "order_name": order.name,
                "current_state": "cancel"
            }

        # Consenti solo 'draft'
        if order.state != 'draft':
            return {
                "error": f"❌ Cancellazione non consentita: ordine in stato '{order.state}'",
                "allowed_from_state": "draft",
                "order_name": order.name,
                "current_state": order.state,
                "solution": "Puoi cancellare solo ordini in bozza. Per ordini confermati, contatta l'amministratore."
            }

        # Cancellazione
        try:
            order.action_cancel()
            
            # Ricarica l'ordine dal database per ottenere lo stato aggiornato
            order = SaleOrder.browse(order.id)
            
            # Verifica che sia stato cancellato
            if order.state != 'cancel':
                _logger.error(f"Ordine {order.name} non cancellato! Stato: {order.state}")
                return {
                    "error": f"❌ Cancellazione fallita: ordine rimasto in stato '{order.state}'",
                    "order_name": order.name,
                    "order_id": order.id,
                    "current_state": order.state
                }

            return {
                "success": True,
                "order_id": order.id,
                "order_name": order.name,
                "previous_state": "draft",
                "current_state": order.state,
                "message": f"✅ Ordine {order.name} cancellato con successo"
            }
        
        except Exception as e:
            _logger.error(f"Errore cancellazione ordine {order.name}: {str(e)}")
            return {
                "error": f"Errore durante la cancellazione: {str(e)}",
                "order_name": order.name,
                "order_id": order.id
            }

    
    @api.model
    def update_confirmed_sales_order(self, order_name=None, order_id=None, order_lines_updates=None, scheduled_date=None):
        """
        Modifica Sales Order in stato 'sale' (confermato) rimantenendo sincronizzazione con delivery.
        
        ⚠️ ATTENZIONE: Questa operazione comporta:
        - Annullamento dei delivery NON ancora evasi (assigned/waiting/confirmed)
        - Sblocco ordine a 'draft'
        - Applicazione modifiche
        - Riconferma ordine (genera NUOVI delivery con quantità aggiornate)
        
        ❌ BLOCCO: Non può essere usata se delivery già validati (stato 'done')
        
        FLUSSO:
        1. Verifica che nessun delivery sia già stato evaso
        2. Annulla picking in sospeso
        3. Sblocca ordine a 'draft'
        4. Applica modifiche alle righe ordine
        5. Riconferma ordine (genera nuovi picking sincronizzati)
        6. Applica scheduled_date ai nuovi picking
        
        Args:
            order_name (str): Nome ordine (es. "SO042")
            order_id (int): ID ordine (alternativa a order_name)
            order_lines_updates (list): Stesso formato di update_sales_order()
                [
                    {"line_id": 123, "quantity": 10},  # Modifica riga
                    {"product_id": 25, "quantity": 5},  # Aggiungi riga
                    {"line_id": 124, "delete": True},   # Elimina riga
                ]
            scheduled_date (str/datetime): Data consegna pianificata
        
        Returns:
            Dict con successo/errore, picking cancellati e nuovi picking creati
        """
        #generazione automatica di nuovi delivery disabilitata; l'ordine rimane in bozza dopo le modifiche
        SaleOrder = self.env['sale.order']
        SaleOrderLine = self.env['sale.order.line']
        Product = self.env['product.product']
        
        # Trova ordine
        if order_id:
            order = SaleOrder.browse(order_id)
        elif order_name:
            order = SaleOrder.search([('name', '=', order_name)], limit=1)
        else:
            return {"error": "Specificare order_name o order_id"}
        
        if not order.exists():
            return {"error": f"Ordine '{order_name or order_id}' non trovato"}
        
        # Verifica stato
        if order.state not in ('sale', 'done'):
            return {
                "error": f"❌ Questa funzione è solo per ordini confermati (stato 'sale')",
                "current_state": order.state,
                "current_state_display": dict(order._fields['state'].selection).get(order.state),
                "solution": "Usa update_sales_order() per ordini in bozza (draft/sent)"
            }
        
        # ========== verifica delivery non evasi ==========
        done_pickings = order.picking_ids.filtered(lambda p: p.state == 'done')
        if done_pickings:
            return {
                "error": f"❌ Impossibile modificare: {len(done_pickings)} delivery già evasi",
                "done_pickings": [
                    {
                        "name": p.name,
                        "date_done": p.date_done.strftime("%Y-%m-%d %H:%M") if p.date_done else None,
                        "products": [{
                            "product": m.product_id.name,
                            "qty_done": m.quantity_done
                        } for m in p.move_ids if m.quantity_done > 0]
                    } for p in done_pickings
                ],
                "reason": "Una volta spedita la merce, non puoi modificare l'ordine retroattivamente",
                "solutions": [
                    "1. Crea un NUOVO ordine per prodotti aggiuntivi",
                    "2. Gestisci differenze con Note di Credito/Debito (modulo Accounting)",
                    "3. Crea un Reso (Return) se serve correggere quantità già spedite"
                ],
                "note": "Questo blocco protegge l'integrità dei dati: le spedizioni fisiche non possono essere retroattivamente modificate"
            }
        # ==========================================================================
        
        if not order_lines_updates and not scheduled_date:
            return {"error": "Specificare order_lines_updates o scheduled_date"}
        
        try:
            # 1. Trova e annulla picking in sospeso
            pending_pickings = order.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel'))
            cancelled_picking_info = []
            
            _logger.info(f"update_confirmed_sales_order: Annullando {len(pending_pickings)} picking per {order.name}")
            
            for picking in pending_pickings:
                cancelled_picking_info.append({
                    "name": picking.name,
                    "state_before": picking.state,
                    "scheduled_date": picking.scheduled_date.strftime("%Y-%m-%d %H:%M") if picking.scheduled_date else None
                })
                picking.action_cancel()
            
            # 2. Sblocca ordine a draft
            order.action_draft()
            _logger.info(f"update_confirmed_sales_order: Ordine {order.name} sbloccato a draft")
            
            # 3. Applica modifiche righe ordine
            updated_lines = []
            added_lines = []
            deleted_lines = []
            
            if order_lines_updates:
                for update in order_lines_updates:
                    # Caso 1: Elimina riga
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
                        product = Product.browse(update.get('product_id'))
                        if not product.exists():
                            continue
                         
                        price_unit = update.get('price_unit', product.list_price)
                         
                        new_line = SaleOrderLine.create({
                            'order_id': order.id,
                            'product_id': product.id,
                            'product_uom_qty': update['quantity'],
                            'product_uom': product.uom_id.id,
                            'price_unit': price_unit,
                        })
                        added_lines.append({
                            'product': product.name,
                            'quantity': update['quantity'],
                            'price_unit': price_unit
                        })
            
            # 4. Aggiorna commitment_date se fornito
            if scheduled_date:
                if isinstance(scheduled_date, str):
                    from datetime import datetime
                    try:
                        if ' ' in scheduled_date:
                            scheduled_date = datetime.strptime(scheduled_date, "%Y-%m-%d %H:%M:%S")
                        else:
                            scheduled_date = datetime.strptime(scheduled_date, "%Y-%m-%d")
                    except ValueError:
                        return {"error": f"Formato data non valido: {scheduled_date}. Usa 'YYYY-MM-DD' o 'YYYY-MM-DD HH:MM:SS'"}
                
                order.write({'commitment_date': scheduled_date})
            
            # 5. aggiornamento cache e commit
            self.env.flush_all()
            order.invalidate_recordset()
            order.order_line.invalidate_recordset()
            self.env.cr.commit()
            _logger.info(f"💾 Commit eseguito dopo modifica ordine confermato {order.name}")
            
            # 6. Ricarica ordine dal database
            order = self.env['sale.order'].browse(order.id)

            # riconferma automatica dell'ordine e generazione nuovi picking disattivata
            # order.action_confirm()
            # _logger.info(f"update_confirmed_sales_order: Ordine {order.name} riconfermato, nuovi picking generati")
            # 
            # # 6. Applica scheduled_date ai nuovi picking
            # new_picking_info = []
            # if scheduled_date and order.picking_ids:
            #     for picking in order.picking_ids:
            #         picking.write({'scheduled_date': scheduled_date})
            #         new_picking_info.append({
            #             "name": picking.name,
            #             "state": picking.state,
            #             "scheduled_date": picking.scheduled_date.strftime("%Y-%m-%d %H:%M") if picking.scheduled_date else None
            #         })
            # else:
            #     new_picking_info = [
            #         {
            #             "name": p.name,
            #             "state": p.state,
            #             "scheduled_date": p.scheduled_date.strftime("%Y-%m-%d %H:%M") if p.scheduled_date else None
            #         } for p in order.picking_ids
            #     ]
            # 
            # return {
            #     "success": True,
            #     "message": f"✅ Ordine {order.name} modificato e riconfermato con successo",
            #     "order_id": order.id,
            #     "order_name": order.name,
            #     "state": order.state,
            #     "amount_total": order.amount_total,
            #     "updated_lines": updated_lines,
            #     "added_lines": added_lines,
            #     "deleted_lines": deleted_lines,
            #     "cancelled_pickings": cancelled_picking_info,
            #     "new_pickings": new_picking_info,
            #     "warnings": [
            #         "⚠️ I delivery precedenti sono stati annullati e sostituiti con nuovi delivery",
            #         "Il magazzino dovrà processare i NUOVI picking generati",
            #         "Le prenotazioni stock precedenti sono state rilasciate"
            #     ],
            #     "note": f"Totale picking annullati: {len(cancelled_picking_info)} | Nuovi picking: {len(new_picking_info)}"
            # }
            # Fine blocco disattivato
            result = {
                "success": True,
                "message": f"✅ Ordine {order.name} modificato con successo (consegne non generate automaticamente)",
                "order_id": order.id,
                "order_name": order.name,
                "state": order.state,
                "amount_total": order.amount_total,
                "updated_lines": updated_lines,
                "added_lines": added_lines,
                "deleted_lines": deleted_lines,
                "cancelled_pickings": cancelled_picking_info,
                "new_pickings": [],
                "warnings": [
                    "⚠️ I delivery precedenti sono stati annullati; nessun nuovo delivery creato automaticamente",
                    "Le prenotazioni stock precedenti sono state rilasciate"
                ],
                "note": f"Totale picking annullati: {len(cancelled_picking_info)} | Nuovi picking: 0"
            }
            return result
        except Exception as e:
            _logger.exception(f"Errore in update_confirmed_sales_order per {order.name}")
            return {
                "error": f"Errore durante modifica ordine confermato: {str(e)}",
                "order_name": order.name,
                "order_state": order.state,
                "note": "L'ordine potrebbe essere in uno stato intermedio. Verifica manualmente."
            }
    
    @api.model
    def update_delivery(self, picking_name=None, picking_id=None, move_updates=None):
        """
        ⚠️ Modifica delivery NON collegati a Sales Orders.
        
        IMPORTANTE: I delivery generati da ordini di vendita NON possono essere modificati direttamente.
        La modifica deve avvenire tramite il Sales Order per mantenere la sincronizzazione.
        
        QUANDO USARE:
        ✅ Delivery diretti (creati con create_delivery_order)
        ✅ Transfer interni
        ✅ Movimenti senza origine commerciale
        
        QUANDO NON USARE:
        ❌ Delivery generati da Sales Orders → Usa update_sales_order() o update_confirmed_sales_order()
        
        Args:
            picking_name (str): Nome del delivery (es. "WH/OUT/00025")
            picking_id (int): ID del picking (alternativa a picking_name)
            move_updates (list): [
                {"move_id": 123, "quantity": 10},  # Modifica movimento esistente
                {"product_id": 25, "quantity": 5},  # Aggiungi nuovo movimento
                {"move_id": 124, "delete": True},   # Elimina movimento
            ]
        
        Returns:
            Dict con info aggiornamento o errore se collegato a Sales Order
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
        
        # ========== blocca se collegato a Sales Order ==========
        if picking.sale_id:
            return {
                "error": f"❌ Impossibile modificare delivery {picking.name}: è collegato all'ordine di vendita {picking.sale_id.name}",
                "reason": "I delivery generati da Sales Orders devono essere modificati tramite l'ordine, non direttamente",
                "sale_order_id": picking.sale_id.id,
                "sale_order_name": picking.sale_id.name,
                "sale_order_state": picking.sale_id.state,
                "solutions": {
                    "if_draft_or_sent": f"Usa update_sales_order(order_name='{picking.sale_id.name}', ...) per modificare l'ordine",
                    "if_confirmed": f"Usa update_confirmed_sales_order(order_name='{picking.sale_id.name}', ...) per modificare ordine confermato",
                    "alternative": "Se devi consegnare quantità diverse dal previsto, usa validate_delivery() con backorder"
                },
                "current_order_state": picking.sale_id.state,
                "note": "Questa protezione previene disallineamenti tra quantità ordinate e spedite"
            }
        # ==========================================================================
        
        # Controlla se il picking è modificabile
        if picking.state == 'done':
            return {
                "error": f"❌ Delivery {picking.name} già validato (stato: done)",
                "reason": "Non è possibile modificare un delivery già evaso"
            }
        
        if picking.state == 'cancel':
            return {"error": f"❌ Delivery {picking.name} annullato, non modificabile"}
        
        # Applica le modifiche ai movimenti di stock
        try:
            if move_updates is None:
                move_updates = []
            updated_moves = []
            added_moves = []
            deleted_moves = []
            
            for move_update in move_updates:
                # Modifica movimento esistente
                if move_update.get('move_id') and not move_update.get('delete'):
                    move = StockMove.browse(move_update['move_id'])
                    if move.exists() and move.picking_id.id == picking.id:
                        old_qty = move.product_uom_qty
                        move.write({'product_uom_qty': move_update['quantity']})
                        updated_moves.append({
                            "move_id": move.id,
                            "product": move.product_id.name,
                            "old_quantity": old_qty,
                            "new_quantity": move_update['quantity']
                        })
                
                # Elimina movimento esistente
                if move_update.get('delete') and move_update.get('move_id'):
                    move = StockMove.browse(move_update['move_id'])
                    if move.exists() and move.picking_id.id == picking.id:
                        deleted_moves.append(move.product_id.name)
                        move.unlink()
                        continue
                
                # Aggiungi nuovo movimento
                if move_update.get('product_id') and move_update.get('quantity'):
                    product = Product.browse(move_update['product_id'])
                    if not product.exists():
                        continue
                    new_move = StockMove.create({
                        'picking_id': picking.id,
                        'product_id': product.id,
                        'product_uom_qty': move_update['quantity'],
                        'product_uom': product.uom_id.id,
                        'name': product.name,
                        'location_id': picking.location_id.id,
                        'location_dest_id': picking.location_dest_id.id,
                    })
                    added_moves.append({
                        "product": product.name,
                        "quantity": move_update['quantity']
                    })
            
            # Forza flush e invalidazione cache
            self.env.flush_all()
            picking.invalidate_recordset()
            picking.move_ids.invalidate_recordset()
            self.env.cr.commit()
            _logger.info(f"💾 Commit eseguito dopo aggiornamento delivery {picking.name}")
            
            # Ricarica picking
            picking = StockPicking.browse(picking.id)
            
            # Ritorna risultato
            return {
                "success": True,
                "message": f"Delivery {picking.name} aggiornato",
                "picking_id": picking.id,
                "picking_name": picking.name,
                "updated_moves": updated_moves,
                "added_moves": added_moves,
                "deleted_moves": deleted_moves,
            }
        except Exception as e:
            return {"error": f"Errore durante aggiornamento delivery: {str(e)}"}
    
    @api.model
    def get_orders_summary(self, period='month', state=None, limit=10):
        """
        Ottiene una panoramica degli ordini di vendita (numero, fatturato, ecc.), filtrati per periodo e stato.
        
        Args:
            period (str): 'day', 'week', 'month', 'year', 'all' (default 'month')
            state (str): stato degli ordini ('draft', 'sent', 'sale', 'done', 'cancel')
            limit (int): numero massimo di ordini da includere nella lista dettagliata (default 10)
        
        Returns:
            Dict con statistiche e lista ordini
        """
        SaleOrder = self.env['sale.order']
        
        # Costruisci dominio base
        domain = [('state', 'in', ['sale', 'done'])]
        
        # Filtro temporale
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
    def get_sales_order_details(self, order_name=None, order_id=None, internal=False):
        """
        Ottiene dettagli completi di un ordine di vendita, incluse righe prodotto e delivery collegati.
        
        Args:
            order_name: Nome ordine (es. "S00034")
            order_id: ID ordine (alternativa a order_name)
            internal: Se True, ritorna solo dati essenziali per l'AI (senza formattazione)
        
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
        
        # REFRESH completo
        order.invalidate_recordset()  # Invalida cache
        order.order_line.invalidate_recordset()  # Invalida cache righe
        order.picking_ids.invalidate_recordset()  # Invalida cache picking
        if hasattr(order, 'invoice_ids'):
            order.invoice_ids.invalidate_recordset()  # Invalida cache fatture
        _logger.info(f"🔄 Cache completamente invalidata per ordine {order.name} - rilettura dati freschi")
        
        # Ricarica l'ordine dal database
        order = SaleOrder.browse(order.id)
        
        # ritorna solo dati essenziali per l'AI
        if internal:
            return {
                "order_id": order.id,
                "order_name": order.name,
                "order_lines": [
                    {
                        "line_id": line.id,
                        "product_id": line.product_id.id,
                        "product_name": line.product_id.name,
                        "quantity": line.product_uom_qty
                    } for line in order.order_line
                ],
                "_internal_call": True
            }
        
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
        if hasattr(order, 'invoice_ids'):
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
            del stats["order_ids"]  
            top_products.append(stats)
        
        # Ordina per quantità venduta decrescente
        top_products.sort(key=lambda x: x["total_qty_sold"], reverse=True)
        
        return {
            "period": period,
            "total_products": len(top_products),
            "top_products": top_products[:limit]
        }
