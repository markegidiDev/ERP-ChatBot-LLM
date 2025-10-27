from odoo import models, api
from markupsafe import Markup
import requests
import json
import logging
import re

_logger = logging.getLogger(__name__)

# Marker for pending sales order confirmation
PENDING_SO_MARKER = "[PENDING_SO]"


def _balanced_json_extract_simple(txt):
    """Estrae un JSON bilanciato da una stringa (versione semplice per ai_chatbot)."""
    if not txt:
        return None
    i = txt.find('{')
    if i == -1:
        return None
    depth = 0
    for k, ch in enumerate(txt[i:], start=i):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return txt[i:k+1]
    return None


def format_html_response(text):
    """
    Converte testo semplice in HTML formattato per chat Odoo.
    - Sostituisce \n\n con <br/><br/>
    - Sostituisce \n con <br/>
    - Evidenzia checkmark e simboli
    - Formatta liste puntate
    """
    if not text:
        return Markup("")
    
    # Sostituisci doppi a capo con doppio <br/>
    text = text.replace('\n\n', '<br/><br/>')
    
    # Sostituisci singoli a capo con <br/>
    text = text.replace('\n', '<br/>')
    
    # Evidenzia titoli (linee che iniziano con emoji seguito da testo maiuscolo)
    text = re.sub(r'(^|<br/>)(📦|✅|⚠️|🔍|💰|📊)\s*([A-Z][^<]*?)(<br/>|$)', 
                  r'\1<strong>\2 \3</strong>\4', text)
    
    # Evidenzia righe che iniziano con "✅" o "⚠️" o "❌"
    text = re.sub(r'(^|<br/>)(✅|⚠️|❌)\s*([^<]+?)(<br/>|$)', 
                  r'\1<strong>\2 \3</strong>\4', text)
    
    # Formatta liste puntate (• item)
    text = re.sub(r'(^|<br/>)•\s*([^<]+?)(<br/>|$)', 
                  r'\1  • <em>\2</em>\3', text)
    
    # Evidenzia codici ordine/delivery (SO123, WH/OUT/00123)
    text = re.sub(r'\b(SO\d+|WH/(?:OUT|IN)/\d+)\b', 
                  r'<code>\1</code>', text)
    
    # Evidenzia numeri con frecce (10 → 15)
    text = re.sub(r'(\d+)\s*→\s*(\d+)', 
                  r'<strong>\1 → \2</strong>', text)
    
    return Markup(text)

class DiscussChannel(models.Model):
    _inherit = 'discuss.channel'
    
    @api.model
    def _get_gemini_response(self, config, messages):
        """Chiama l'API di Gemini"""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{config.model_name}:generateContent"
        
        # Costruisci il payload per Gemini
        contents = []
        
        # Aggiungi messaggi della conversazione (SENZA system prompt come messaggi finti)
        for msg in messages:
            role = "user" if msg['role'] == 'user' else "model"
            contents.append({
                "role": role,
                "parts": [{"text": msg['content']}]
            })
        
        # Costruisci payload con system_instruction nativo di Gemini
        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": config.temperature,
                "maxOutputTokens": config.max_tokens,
            }
        }
        
        # Aggiungi system_instruction se il prompt è definito
        if config.system_prompt:
            payload["system_instruction"] = {
                "parts": [{"text": config.system_prompt}]
            }
            _logger.debug(f"System instruction presente ({len(config.system_prompt)} caratteri)")
        else:
            _logger.debug("System instruction omesso (prompt vuoto/None)")
        
        headers = {
            "Content-Type": "application/json"
        }
        
        try:
            response = requests.post(
                url,
                params={"key": config.api_key},
                headers=headers,
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            
            data = response.json()
            
            # Log completo della risposta per debug
            _logger.info(f"Gemini API response: {json.dumps(data, indent=2)}")
            
            # Gestione robusta della risposta
            if 'candidates' not in data or len(data['candidates']) == 0:
                _logger.error(f"Nessun candidate nella risposta Gemini: {data}")
                return "Errore: risposta API senza risultati"
            
            candidate = data['candidates'][0]
            
            # Controlla se la risposta è stata bloccata dai safety filters
            if 'finishReason' in candidate and candidate['finishReason'] != 'STOP':
                finish_reason = candidate.get('finishReason', 'UNKNOWN')
                safety_ratings = candidate.get('safetyRatings', [])
                _logger.warning(f"Risposta bloccata: {finish_reason}, safety: {safety_ratings}")
                return f"La risposta è stata bloccata per motivi di sicurezza ({finish_reason})"
            
            # Estrai il testo in modo sicuro
            if 'content' not in candidate:
                _logger.error(f"Campo 'content' mancante in candidate: {candidate}")
                return "Errore: risposta API malformata (manca 'content')"
            
            content = candidate['content']
            if 'parts' not in content or len(content['parts']) == 0:
                _logger.error(f"Campo 'parts' mancante o vuoto in content: {content}")
                return "Errore: risposta API malformata (manca 'parts')"
            
            text = content['parts'][0].get('text', '')
            if not text:
                _logger.warning(f"Testo vuoto nella risposta: {content}")
                return "Errore: risposta AI vuota"
            
            return text
                
        except requests.exceptions.RequestException as e:
            _logger.error(f"Errore chiamata Gemini API: {e}")
            return f"Errore di connessione all'AI: {str(e)}"
        except KeyError as e:
            _logger.error(f"Errore parsing risposta Gemini: {e}, data: {data if 'data' in locals() else 'N/A'}")
            return f"Errore: formato risposta API non valido ({e})"
        except Exception as e:
            _logger.error(f"Errore imprevisto Gemini: {e}", exc_info=True)
            return f"Errore imprevisto: {str(e)}"
    
    @api.model
    def _get_available_functions(self):
        """Definisce le funzioni disponibili per l'AI"""
        return {
            "get_stock_info": {
                "description": "Ottiene informazioni sullo stock di un prodotto specifico",
                "parameters": {
                    "product_name": "Nome del prodotto da cercare"
                }
            },
            "search_partners": {
                "description": "Cerca clienti/partner per nome/email/telefono",
                "parameters": {
                    "search_term": "Testo da cercare (es. 'Marco')",
                    "limit": "Numero massimo risultati (default 5)"
                }
            },
            "search_products": {
                "description": "Cerca prodotti nel catalogo",
                "parameters": {
                    "search_term": "Termine di ricerca (opzionale)"
                }
            },
            "get_pending_orders": {
                "description": "Ottiene ordini in sospeso. Può filtrare per tipo: ricezioni (incoming) o consegne (outgoing)",
                "parameters": {
                    "order_type": "Opzionale: 'incoming' per ricezioni, 'outgoing' per consegne. Se omesso mostra tutti",
                    "limit": "Numero massimo risultati (default 10)"
                }
            },
            "get_delivery_details": {
                "description": "Ottiene dettagli completi di un Delivery/Transfer, inclusi TUTTI i movimenti con move_id. USA QUESTA funzione PRIMA di update_delivery per sapere quali prodotti ci sono e i loro move_id",
                "parameters": {
                    "picking_name": "Nome del delivery (es. 'WH/OUT/00013') OPPURE",
                    "picking_id": "ID numerico del picking"
                }
            },
            "validate_delivery": {
                "description": "Valida ed evade un ordine di consegna (spedizione fisica). Scarica lo stock dal magazzino",
                "parameters": {
                    "picking_id": "ID numerico del picking (es. 35) OPPURE",
                    "picking_name": "Nome del delivery (es. 'WH/OUT/00035')"
                }
            },
            "process_delivery_decision": {
                "description": "Applica la scelta utente dopo tentativo di validazione quando quantità non completamente prenotate. Usa wizard nativi Odoo per gestire backorder o trasferimento immediato",
                "parameters": {
                    "picking_id": "ID numerico del picking (es. 35) OPPURE",
                    "picking_name": "Nome del delivery (es. 'WH/OUT/00035')",
                    "decision": "Scelta utente: 'backorder' (crea backorder) | 'no_backorder' (scarta residuo) | 'immediate' (trasferimento immediato)"
                }
            },
            "create_sales_order": {
                "description": "FLUSSO STANDARD per 'ordini da evadere': crea un Sales Order e lo conferma. La conferma genera automaticamente i Delivery secondo le regole di magazzino (1/2/3 step). Assicura tracciabilità commerciale completa (preventivo→ordine→consegna→fattura) con prezzi, sconti e tasse corretti",
                "parameters": {
                    "partner_name": "Nome del cliente",
                    "order_lines": "Lista righe: [{'product_id': 1, 'quantity': 5, 'price_unit': 100.0}]. price_unit è opzionale (usa listino se omesso)",
                    "confirm": "Opzionale (default True): se True conferma l'ordine e genera i picking automaticamente",
                    "scheduled_date": "Opzionale: Data pianificata consegna (formato ISO: '2025-10-21' o '2025-10-21 14:00:00'). Se specificata, imposta la data del delivery"
                }
            },
            "create_partner": {
                "description": "Crea un nuovo cliente (res.partner) se non esiste. Usa questo quando l'utente chiede di creare un ordine per un cliente non presente.",
                "parameters": {
                    "name": "Nome completo del cliente (obbligatorio)",
                    "email": "Email (opzionale)",
                    "phone": "Telefono (opzionale)",
                    "mobile": "Cellulare (opzionale)",
                    "street": "Indirizzo (opzionale)",
                    "city": "Città (opzionale)",
                    "zip": "CAP (opzionale)",
                    "country_code": "Codice nazione ISO-2 es. IT (opzionale)",
                    "vat": "Partita IVA (opzionale)",
                    "company_name": "Azienda collegata (opzionale)",
                    "is_company": "True se il partner è un'azienda (default False)"
                }
            },
            "create_delivery_order": {
                "description": "SOLO per casi ECCEZIONALI (omaggi, sostituzioni, campionature): crea un Transfer diretto senza Sales Order. ATTENZIONE: salta prezzi, condizioni commerciali e collegamento fatturazione. Per ordini commerciali normali usa create_sales_order",
                "parameters": {
                    "partner_name": "Nome del destinatario",
                    "product_items": "Lista prodotti: [{'product_id': 1, 'quantity': 5}]"
                }
            },
            "update_sales_order": {
                "description": "Aggiorna un Sales Order esistente (SOLO in stato draft/sent): modifica quantità, aggiungi/rimuovi righe, cambia data consegna. NON funziona su ordini già confermati",
                "parameters": {
                    "order_name": "Nome ordine (es. 'SO042') OPPURE",
                    "order_id": "ID numerico dell'ordine",
                    "order_lines_updates": "Lista modifiche: [{'line_id': 123, 'quantity': 10}, {'product_id': 25, 'quantity': 5}, {'line_id': 124, 'delete': True}]",
                    "scheduled_date": "Data consegna pianificata (formato ISO: '2025-10-21' o '2025-10-21 14:00:00') - OPZIONALE"
                }
            },
            "update_delivery": {
                "description": "Modifica quantità su Delivery/Transfer NON ancora validato (state != done). Per modificare delivery già evasi è impossibile",
                "parameters": {
                    "picking_name": "Nome delivery (es. 'WH/OUT/00025') OPPURE",
                    "picking_id": "ID numerico del picking",
                    "move_updates": "Lista modifiche: [{'move_id': 123, 'quantity': 10}, {'product_id': 25, 'quantity': 5}, {'move_id': 124, 'delete': True}]"
                }
            },
            "get_sales_overview": {
                "description": "Ottiene panoramica ordini di vendita con statistiche e lista ordini. Ideale per vedere situazione vendite nel periodo",
                "parameters": {
                    "period": "Periodo: 'day', 'week', 'month' (default), 'year', 'all'",
                    "state": "Filtra per stato ('draft', 'sent', 'sale', 'done', 'cancel'). Se omesso mostra tutti",
                    "limit": "Massimo ordini (default 100)"
                }
            },
            "get_sales_order_details": {
                "description": "Ottiene dettagli completi di un ordine di vendita specifico: righe prodotto, delivery collegati, fatture",
                "parameters": {
                    "order_name": "Nome ordine (es. 'S00034') OPPURE",
                    "order_id": "ID numerico ordine"
                }
            },
            "get_top_customers": {
                "description": "Classifica top clienti per fatturato nel periodo con statistiche vendite",
                "parameters": {
                    "period": "Periodo: 'month' (default), 'quarter', 'year', 'all'",
                    "limit": "Numero clienti da mostrare (default 10)"
                }
            },
            "get_products_sales_stats": {
                "description": "Statistiche prodotti più venduti nel periodo con quantità e fatturato",
                "parameters": {
                    "period": "Periodo: 'month' (default), 'quarter', 'year', 'all'",
                    "limit": "Numero prodotti da mostrare (default 20)"
                }
            }
        }
    
    @api.model
    def _execute_function(self, function_name, parameters):
        """Esegue una funzione di warehouse operations"""
        warehouse_ops = self.env['warehouse.operations']
        
        try:
            if function_name == 'get_stock_info':
                return warehouse_ops.get_stock_info(**parameters)
            elif function_name == 'search_partners':
                call_params = dict(parameters)
                if 'limit' in call_params:
                    try:
                        call_params['limit'] = int(call_params['limit'])
                    except (TypeError, ValueError):
                        call_params['limit'] = 5
                return warehouse_ops.search_partners(**call_params)
            elif function_name == 'search_products':
                call_params = dict(parameters)
                # Cast limit to int (AI può passarlo come stringa)
                if 'limit' in call_params:
                    try:
                        call_params['limit'] = int(call_params['limit'])
                    except (TypeError, ValueError):
                        call_params['limit'] = 100  # ✅ Default più alto per "mostra tutti"
                else:
                    # Se l'AI non specifica limit, usa un valore alto per "mostra tutti"
                    call_params['limit'] = 100
                
                result = warehouse_ops.search_products(**call_params)
                
                # LOG DEBUG: verifica che list_price sia presente
                _logger.info(f"=== search_products: {len(result)} risultati (limit={call_params.get('limit')}) ===")
                for prod in result[:5]:  # Mostra solo i primi 5 per non intasare log
                    _logger.info(f"  • {prod['name']} (ID: {prod['id']}) - €{prod.get('list_price', 'N/A')} - {prod.get('qty_available', 'N/A')} unità")
                if len(result) > 5:
                    _logger.info(f"  ... e altri {len(result) - 5} prodotti")
                _logger.info(f"=====================================")
                
                return result
            elif function_name == 'get_pending_orders':
                call_params = dict(parameters)
                if 'limit' in call_params:
                    try:
                        call_params['limit'] = int(call_params['limit'])
                    except (TypeError, ValueError):
                        call_params['limit'] = 10
                return warehouse_ops.get_pending_orders(**call_params)
            elif function_name == 'get_delivery_details':
                call_params = dict(parameters)
                if 'picking_id' in call_params:
                    try:
                        call_params['picking_id'] = int(call_params['picking_id'])
                    except (TypeError, ValueError):
                        return {"error": "picking_id deve essere un numero"}
                return warehouse_ops.get_delivery_details(**call_params)
            elif function_name == 'validate_delivery':
                # Supporta picking_id O picking_name
                call_params = dict(parameters)
                if 'picking_id' in call_params:
                    try:
                        call_params['picking_id'] = int(call_params['picking_id'])
                    except (TypeError, ValueError):
                        return {"error": "picking_id deve essere un numero"}
                return warehouse_ops.validate_delivery(**call_params)
            
            elif function_name == 'process_delivery_decision':
                # Gestione wizard backorder/immediate transfer
                call_params = dict(parameters)
                if 'picking_id' in call_params:
                    try:
                        call_params['picking_id'] = int(call_params['picking_id'])
                    except (TypeError, ValueError):
                        return {"error": "picking_id deve essere un numero"}
                return warehouse_ops.process_delivery_decision(**call_params)
            
            elif function_name == 'create_sales_order':
                # VALIDAZIONE PARAMETRI - Correggi errori comuni dell'AI
                call_params = dict(parameters)
                
                # Correggi "customer" → "partner_name"
                if 'customer' in call_params:
                    _logger.warning("AI ha usato 'customer' invece di 'partner_name' - correggo automaticamente")
                    call_params['partner_name'] = call_params.pop('customer')
                
                # Correggi "cliente" → "partner_name"
                if 'cliente' in call_params:
                    _logger.warning("AI ha usato 'cliente' invece di 'partner_name' - correggo automaticamente")
                    call_params['partner_name'] = call_params.pop('cliente')
                
                # Blocca "products" (impossibile correggere automaticamente)
                if 'products' in call_params:
                    _logger.error("AI ha usato 'products' invece di 'order_lines' - impossibile correggere")
                    return {
                        "error": "Parametri non validi",
                        "details": "Usa 'partner_name' e 'order_lines', NON 'customer' e 'products'",
                        "correct_format": "[FUNCTION:create_sales_order|partner_name:CLIENTE|order_lines:[{\"product_id\":ID,\"quantity\":QTY}]|confirm:true]",
                        "ai_instruction": "RIPROVA con il formato corretto sopra. USA search_products PRIMA per trovare il product_id."
                    }
                
                # Verifica parametri obbligatori
                if 'partner_name' not in call_params:
                    return {
                        "error": "Parametro obbligatorio 'partner_name' mancante",
                        "ai_instruction": "USA: partner_name (NON customer, NON cliente)"
                    }
                
                if 'order_lines' not in call_params:
                    return {
                        "error": "Parametro obbligatorio 'order_lines' mancante",
                        "ai_instruction": "USA: order_lines:[{\"product_id\":ID,\"quantity\":QTY}] (NON products, NON items). Devi chiamare search_products PRIMA per ottenere il product_id."
                    }
                
                # Gestisci confirm
                if 'confirm' in call_params:
                    confirm_val = call_params['confirm']
                    if isinstance(confirm_val, str):
                        call_params['confirm'] = confirm_val.lower() in ('true', '1', 'yes')
                    else:
                        call_params['confirm'] = bool(confirm_val)
                
                # Gestisci scheduled_date (converte stringa ISO in datetime se necessario)
                if 'scheduled_date' in call_params and call_params['scheduled_date']:
                    scheduled_str = call_params['scheduled_date']
                    if isinstance(scheduled_str, str):
                        try:
                            from datetime import datetime
                            # Prova formati: "2025-10-21" o "2025-10-21 14:00:00"
                            if ' ' in scheduled_str:
                                call_params['scheduled_date'] = datetime.strptime(scheduled_str, "%Y-%m-%d %H:%M:%S")
                            else:
                                call_params['scheduled_date'] = datetime.strptime(scheduled_str, "%Y-%m-%d")
                        except ValueError as e:
                            _logger.warning(f"Formato data non valido '{scheduled_str}': {e} - ignoro scheduled_date")
                            call_params.pop('scheduled_date', None)
                
                # 🚨 GATE DI CONFERMA: NON eseguire create_sales_order direttamente
                # Invece, restituisci un marker per richiedere conferma all'utente
                _logger.warning("⚠️ AI ha tentato create_sales_order senza conferma - RICHIEDO CONFERMA")
                
                # Prepara JSON per il marker (converti datetime in stringa)
                marker_params = dict(call_params)
                if 'scheduled_date' in marker_params and hasattr(marker_params['scheduled_date'], 'strftime'):
                    marker_params['scheduled_date'] = marker_params['scheduled_date'].strftime("%Y-%m-%d")
                
                # Calcola totale stimato
                total_estimate = 0.0
                product_list = []
                for line in call_params.get('order_lines', []):
                    product_id = line.get('product_id')
                    quantity = line.get('quantity', 0)
                    if product_id:
                        product = self.env['product.product'].browse(product_id)
                        if product.exists():
                            price = line.get('price_unit', product.list_price)
                            total_estimate += price * quantity
                            product_list.append(f"{product.name} ({quantity} pz) - €{price * quantity:.2f}")
                
                # Restituisci messaggio con marker invece di eseguire
                return {
                    "requires_confirmation": True,
                    "pending_params": marker_params,
                    "summary": {
                        "partner_name": call_params.get('partner_name'),
                        "products": product_list,
                        "scheduled_date": marker_params.get('scheduled_date', 'oggi'),
                        "total_estimate": total_estimate
                    },
                    "message": (
                        f"📦 Riepilogo Ordine\n\n"
                        f"Cliente: {call_params.get('partner_name')}\n"
                        f"Prodotti:\n  • " + "\n  • ".join(product_list) + "\n"
                        f"Data consegna: {marker_params.get('scheduled_date', 'oggi')}\n"
                        f"Totale stimato: €{total_estimate:.2f}\n\n"
                        f"{PENDING_SO_MARKER} {json.dumps(marker_params)}\n\n"
                        f"Confermi? (rispondi SÌ/CONFERMO/OK VAI)"
                    )
                }
            elif function_name == 'create_partner':
                call_params = dict(parameters)
                # Normalizza is_company
                if 'is_company' in call_params:
                    v = call_params['is_company']
                    call_params['is_company'] = (str(v).lower() in ('true', '1', 'yes')) if isinstance(v, str) else bool(v)
                return warehouse_ops.create_partner(**call_params)
            
            elif function_name == 'create_delivery_order':
                # VALIDAZIONE per delivery_order
                call_params = dict(parameters)
                
                if 'customer' in call_params:
                    _logger.warning("AI ha usato 'customer' invece di 'partner_name' in delivery_order - correggo")
                    call_params['partner_name'] = call_params.pop('customer')
                
                if 'products' in call_params:
                    return {
                        "error": "Usa 'product_items' invece di 'products'",
                        "correct_format": "product_items:[{\"product_id\":ID,\"quantity\":QTY}]"
                    }
                
                return warehouse_ops.create_delivery_order(**call_params)
            
            elif function_name == 'update_sales_order':
                call_params = dict(parameters)
                
                # Converti order_id se presente
                if 'order_id' in call_params:
                    try:
                        call_params['order_id'] = int(call_params['order_id'])
                    except (TypeError, ValueError):
                        return {"error": "order_id deve essere un numero"}
                
                return warehouse_ops.update_sales_order(**call_params)
            
            elif function_name == 'update_delivery':
                call_params = dict(parameters)
                
                # Converti picking_id se presente
                if 'picking_id' in call_params:
                    try:
                        call_params['picking_id'] = int(call_params['picking_id'])
                    except (TypeError, ValueError):
                        return {"error": "picking_id deve essere un numero"}
                
                return warehouse_ops.update_delivery(**call_params)
            
            # ========== SALES MANAGEMENT ==========
            elif function_name == 'get_sales_overview':
                return warehouse_ops.get_sales_overview(**parameters)
            
            elif function_name == 'get_sales_order_details':
                call_params = dict(parameters)
                if 'order_id' in call_params:
                    try:
                        call_params['order_id'] = int(call_params['order_id'])
                    except (TypeError, ValueError):
                        return {"error": "order_id deve essere un numero"}
                return warehouse_ops.get_sales_order_details(**call_params)
            
            elif function_name == 'get_top_customers':
                return warehouse_ops.get_top_customers(**parameters)
            
            elif function_name == 'get_products_sales_stats':
                return warehouse_ops.get_products_sales_stats(**parameters)
            
            else:
                return {"error": f"Funzione '{function_name}' non trovata"}
        except Exception as e:
            _logger.error(f"Errore esecuzione funzione {function_name}: {e}")
            return {"error": str(e)}
    
    @api.model
    def _parse_ai_function_calls(self, ai_response):
        """
        Analizza la risposta dell'AI per individuare tutte le funzioni richieste.
        Restituisce una lista di tuple (function_name, parameters) e la risposta senza tag.
        """
        # Pattern migliorato: trova [FUNCTION:nome] (case-insensitive) e cattura tutto
        # fino alla ']' corrispondente, gestendo annidamenti di [] nei parametri.
        function_calls = []
        clean_response = ai_response
        
        # Cerca tutti i tag FUNCTION nell'ordine in cui appaiono (case-insensitive)
        idx = 0
        tag_re = re.compile(r"\[(?:FUNCTION|Function|function):")
        while idx < len(clean_response or ""):
            m = tag_re.search(clean_response, idx)
            start = -1 if not m else m.start()
            if start == -1:
                break
            
            _logger.info(f"Parser: trovato tag FUNCTION a posizione {start}")
            
            # Trova il nome della funzione
            name_end = clean_response.find('|', start)
            if name_end == -1:
                name_end = clean_response.find(']', start)
            
            if name_end == -1:
                _logger.warning(f"Parser: non trovo | o ] dopo posizione {start}")
                idx = (start + 10)
                continue
                
            function_name = clean_response[start+10:name_end].strip()
            _logger.info(f"Parser: nome funzione = '{function_name}'")
            # Rimuovi eventuali virgolette attorno al nome funzione
            if (function_name.startswith('"') and function_name.endswith('"')) or \
               (function_name.startswith("'") and function_name.endswith("'")):
                function_name = function_name[1:-1].strip()
            
            # Trova la chiusura del tag, gestendo [] annidati
            bracket_count = 1
            pos = name_end
            tag_end = -1
            
            while pos < len(clean_response) and bracket_count > 0:
                pos += 1
                if pos >= len(clean_response):
                    break
                if clean_response[pos] == '[':
                    bracket_count += 1
                elif clean_response[pos] == ']':
                    bracket_count -= 1
                    if bracket_count == 0:
                        tag_end = pos
                        break
            
            if tag_end == -1:
                idx = start + 10
                continue
            
            # Estrai i parametri
            params_str = clean_response[name_end:tag_end].strip()
            if params_str.startswith('|'):
                params_str = params_str[1:]
            
            parameters = {}
            if params_str:
                # Split per | ma attenzione ai JSON
                parts = []
                current = ""
                bracket_level = 0
                brace_level = 0
                
                for char in params_str:
                    if char == '[':
                        bracket_level += 1
                    elif char == ']':
                        bracket_level -= 1
                    elif char == '{':
                        brace_level += 1
                    elif char == '}':
                        brace_level -= 1
                    elif char == '|' and bracket_level == 0 and brace_level == 0:
                        parts.append(current)
                        current = ""
                        continue
                    current += char
                
                if current:
                    parts.append(current)
                
                # Parse ogni parametro
                for part in parts:
                    if ':' not in part:
                        continue
                    key, value = part.split(':', 1)
                    key = key.strip()
                    value = value.strip()
                    
                    # Prova a parsare come JSON
                    if value.startswith('[') or value.startswith('{'):
                        try:
                            value = json.loads(value)
                        except Exception as e:
                            _logger.warning(f"Impossibile parsare JSON per {key}: {e}")
                    
                    parameters[key] = value
            
            function_calls.append((function_name, parameters))
            
            # Rimuovi il tag dalla risposta
            full_tag = clean_response[start:tag_end+1]
            clean_response = clean_response[:start] + clean_response[tag_end+1:]
            idx = start  # Riparti dalla stessa posizione

        clean_response = clean_response.strip()
        
        _logger.info(f"Parsed {len(function_calls)} function calls")
        if function_calls:
            for fname, fparams in function_calls:
                _logger.info(f"  - {fname}: {fparams}")
        
        return function_calls, clean_response
    
    def message_post(self, **kwargs):
        """Override del metodo message_post per intercettare i messaggi"""
        result = super(DiscussChannel, self).message_post(**kwargs)
        
        # Verifica se è un messaggio in un canale AI
        if not self.name or 'AI Assistant' not in self.name:
            return result
        
        body = kwargs.get('body', '')
        message_type = kwargs.get('message_type', 'comment')
        author_id = kwargs.get('author_id')
        
        # Solo per messaggi dell'utente (non del bot)
        if message_type == 'comment' and author_id:
            author = self.env['res.partner'].browse(author_id)
            
            # Non rispondere ai messaggi del sistema
            if author.name in ['OdooBot', 'System', 'AI Assistant']:
                return result
            
            # 🚨 STEP 0: Check for pending sales order confirmation BEFORE calling AI
            user_message = re.sub(r'<[^>]+>', '', body or '').strip()

            if re.search(r'\b(S[IÌI]|CONFERMO|OK\s*VAI|PERFETTO)\b', user_message, re.I):
                _logger.info("🔍 Possibile conferma rilevata, verifico marker [PENDING_SO]")

                bot_partner_ids = []
                for xmlid in ('base.partner_root', 'base.partner_odoobot'):
                    partner = self.env.ref(xmlid, raise_if_not_found=False)
                    if partner:
                        bot_partner_ids.append(partner.id)

                if bot_partner_ids:
                    last_bot_msg = self.env['mail.message'].search([
                        ('model', '=', self._name),
                        ('res_id', '=', self.id),
                        ('author_id', 'in', bot_partner_ids),
                        ('message_type', '=', 'comment'),
                    ], order='date desc', limit=1)

                    if last_bot_msg and last_bot_msg.body:
                        msg_text = re.sub(r'<[^>]+>', '', last_bot_msg.body or '').strip()
                        _logger.debug(f"Ultimo messaggio bot (200 char): {msg_text[:200]}")

                        # Usa parser a contatore di graffe per JSON annidati
                        text = msg_text
                        idx = text.find(PENDING_SO_MARKER)
                        if idx != -1:
                            jstart = text.find('{', idx)
                            if jstart != -1:
                                depth = 0
                                end = None
                                for k, ch in enumerate(text[jstart:], start=jstart):
                                    if ch == '{':
                                        depth += 1
                                    elif ch == '}':
                                        depth -= 1
                                        if depth == 0:
                                            end = k + 1
                                            break
                                if end:
                                    json_str = text[jstart:end]
                                    _logger.info("✅ Marker [PENDING_SO] trovato: eseguo create_sales_order senza AI")
                                    try:
                                        params = json.loads(json_str)

                                        if 'scheduled_date' in params and isinstance(params['scheduled_date'], str):
                                            from datetime import datetime
                                            scheduled_str = params['scheduled_date']
                                            try:
                                                if ' ' in scheduled_str:
                                                    params['scheduled_date'] = datetime.strptime(scheduled_str, "%Y-%m-%d %H:%M:%S")
                                                else:
                                                    params['scheduled_date'] = datetime.strptime(scheduled_str, "%Y-%m-%d")
                                            except ValueError:
                                                _logger.warning(f"Formato scheduled_date non valido: {scheduled_str}, rimuovo il parametro")
                                                params.pop('scheduled_date', None)

                                        warehouse_ops = self.env['warehouse.operations']
                                        result_create = warehouse_ops.create_sales_order(**params)

                                        lines = []
                                        if isinstance(result_create, dict) and result_create.get('error'):
                                            lines.append(f"⚠️ Errore: {result_create.get('error')}")
                                            if result_create.get('details'):
                                                lines.append(result_create['details'])
                                        else:
                                            order_name = result_create.get('sale_order_name') or result_create.get('order_name')
                                            order_id = result_create.get('sale_order_id') or result_create.get('order_id')
                                            if order_name:
                                                lines.append(f"✅ Ordine creato: {order_name}")
                                            if order_id:
                                                lines.append(f"ID interno: {order_id}")

                                            state = result_create.get('state', 'N/A')
                                            state_map = {'draft': 'Bozza', 'sent': 'Inviato', 'sale': 'Confermato', 'done': 'Evaso'}
                                            lines.append(f"Stato: {state_map.get(state, state)}")

                                            pickings = result_create.get('pickings', [])
                                            if pickings:
                                                lines.append("\nConsegne generate:")
                                                for p in pickings:
                                                    lines.append(f"  • {p.get('picking_name')} - {p.get('scheduled_date', 'N/A')}")

                                            lines.append(f"\nTotale: €{result_create.get('amount_total', 0):.2f}")

                                        self.message_post(
                                            body=format_html_response("\n\n".join(lines) if lines else "Operazione completata."),
                                            message_type='comment',
                                            subtype_xmlid='mail.mt_comment',
                                            author_id=last_bot_msg.author_id.id if last_bot_msg else bot_partner_ids[0],
                                        )

                                        return result
                                    except Exception as e:
                                        _logger.error(f"Errore durante l'esecuzione diretta di create_sales_order: {e}", exc_info=True)
                        else:
                            _logger.info("❌ Nessun marker [PENDING_SO] trovato nell'ultimo messaggio del bot")
                    else:
                        _logger.info("ℹ️ Nessun messaggio del bot trovato per verificare la conferma")
            
            # Chiama l'AI per generare una risposta (solo se non c'era conferma)
            self._generate_ai_response(body)
        
        return result
    
    def _generate_ai_response(self, user_message):
        """Genera e invia una risposta AI"""
        try:
            config = self.env['ai.config'].get_active_config()
            
            # Costruisci la storia della conversazione
            messages = []
            
            # NOTA: Non aggiungiamo più functions_desc qui per risparmiare token
            # Il System Prompt contiene già tutte le istruzioni necessarie
            # functions_desc consumava ~500 token ad ogni messaggio!
            
            messages.append({
                'role': 'user',
                'content': user_message
            })
            
            # Ottieni risposta dall'AI
            ai_response = self._get_gemini_response(config, messages)
            
            # LOG DETTAGLIATO per debug
            _logger.info(f"========== AI RAW RESPONSE ==========")
            _logger.info(f"Response type: {type(ai_response)}")
            _logger.info(f"Response length: {len(ai_response) if ai_response else 0}")
            _logger.info(f"Response repr: {repr(ai_response)}")
            _logger.info(f"Contains [FUNCTION:: {('[FUNCTION:' in (ai_response or ''))}")
            _logger.info(f"========================================")
            
            # Verifica se l'AI vuole eseguire una o più funzioni
            function_calls, clean_response = self._parse_ai_function_calls(ai_response)
            
            # Se il parser non ha trovato nulla ma la risposta contiene '[FUNCTION:',
            # proviamo una pulizia aggressiva e riproviamo
            if not function_calls and '[FUNCTION:' in (ai_response or ''):
                _logger.warning("Parser non ha trovato FUNCTION ma la stringa li contiene. Cleaning + fallback...")
                try:
                    # 1) Pulizia base
                    cleaned = re.sub(r'```.*?```', '', ai_response, flags=re.S)   # rimuovi code blocks
                    cleaned = cleaned.replace('`', '')                            # rimuovi backticks sparsi
                    # normalizza newline DENTRO al tag (case-insensitive su 'function')
                    cleaned = re.sub(
                        r'\[(?:FUNCTION|Function|function):([^\]]+)\]',
                        lambda m: '[FUNCTION:' + m.group(1).replace('\n','').replace('\r','') + ']',
                        cleaned
                    )
                    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
                    _logger.info(f"Cleaned response: {repr(cleaned)}")

                    # 2) Riprova il parser "ricco"
                    function_calls, clean_response = self._parse_ai_function_calls(cleaned)
                    if not function_calls:
                        # 3) Fallback: tag senza parametri -> {} (es. [FUNCTION:search_products])
                        bare = re.findall(r'\[(?:FUNCTION|Function|function):\s*([A-Za-z0-9_]+)\s*\]', cleaned)
                        if bare:
                            function_calls = [(name.strip(), {}) for name in bare]
                            clean_response = re.sub(r'\[(?:FUNCTION|Function|function):[^\]]+\]', '', cleaned).strip()
                            _logger.info(f"✅ Fallback bare FUNCTION: create {len(function_calls)} call(s) with empty params.")
                        else:
                            _logger.error(f"❌ Anche dopo cleaning/fallback non trovo tag. cleaned={cleaned}")

                    # 4) Se abbiamo trovato qualcosa, usa la versione pulita come base
                    if function_calls:
                        ai_response = cleaned

                except Exception:
                    _logger.error("Errore durante cleaning/fallback FUNCTION tags", exc_info=True)

            _logger.info(f"AI response: {ai_response}")
            _logger.info(f"Function calls trovate: {len(function_calls)}")
            _logger.info(f"Clean response: {clean_response}")

            if function_calls:
                # Esegui tutte le funzioni richieste
                executed_calls = []

                for function_name, parameters in function_calls:
                    _logger.info(f"Eseguo funzione: {function_name} con parametri: {parameters}")
                    result = self._execute_function(function_name, parameters)
                    executed_calls.append((function_name, parameters, result))

                # Prepara il messaggio con i risultati per uso interno (summary)
                summary_blocks = []
                for function_name, parameters, result in executed_calls:
                    summary_blocks.append(
                        f"Risultato della funzione {function_name} con parametri {json.dumps(parameters)}: {json.dumps(result, indent=2)}"
                    )

                # Se abbiamo almeno una funzione di scrittura/creazione, NON chiedere
                # all'LLM di riformattare: compongo io la conferma e la pubblico.
                mutating_fns = {'create_sales_order', 'create_partner', 'create_delivery_order', 'validate_delivery'}
                if any(fn in mutating_fns for fn, _, _ in executed_calls):
                    final_response = None
                    
                    for function_name, parameters, result in executed_calls:
                        # 🚨 GATE: Se il risultato richiede conferma, usa SOLO il messaggio formattato
                        if isinstance(result, dict) and result.get('requires_confirmation'):
                            _logger.info("✅ Richiesta conferma per create_sales_order - uso SOLO il campo 'message'")
                            # ✅ FIX: Usa SOLO il messaggio, NON tutto il dict
                            final_response = result.get('message', 'Confermi?')
                            break
                    
                    # Se non abbiamo già un final_response (nessuna conferma richiesta)
                    if final_response is None:
                        lines = []
                        for function_name, parameters, result in executed_calls:
                            # Error handling
                            if isinstance(result, dict) and result.get('error'):
                                lines.append(f"⚠️ Errore eseguendo {function_name}: {result.get('error')}")
                                if result.get('details'):
                                    lines.append(result.get('details'))
                                continue

                            # Success - formatta i risultati più importanti in modo leggibile
                            if function_name == 'create_sales_order':
                                order_name = result.get('sale_order_name') or result.get('order_name')
                                order_id = result.get('sale_order_id') or result.get('order_id')
                                if order_name:
                                    lines.append(f"✅ Ordine creato: {order_name}")
                                if order_id:
                                    lines.append(f"ID interno: {order_id}")
                                
                                # Stato
                                state = result.get('state', 'N/A')
                                state_map = {'draft': 'Bozza', 'sent': 'Inviato', 'sale': 'Confermato', 'done': 'Evaso'}
                                lines.append(f"Stato: {state_map.get(state, state)}")
                                
                                # Picking
                                pickings = result.get('pickings', [])
                                if pickings:
                                    lines.append("\nConsegne generate:")
                                    for p in pickings:
                                        lines.append(f"  • {p.get('picking_name')} - {p.get('scheduled_date', 'N/A')}")
                                
                                lines.append(f"\nTotale: €{result.get('amount_total', 0):.2f}")
                            else:
                                lines.append(f"✅ {function_name} eseguita con successo")
                        
                        final_response = "\n\n".join(lines) if lines else "Operazione completata."

                else:
                    # Nessuna operazione mutante: possiamo chiedere all'LLM di formattare la risposta
                    follow_up_messages = messages + [
                        {'role': 'assistant', 'content': clean_response if clean_response else "Ho capito, ecco i risultati."},
                        {'role': 'user', 'content': "\n\n".join(summary_blocks) + 
                            "\n\nGenera una risposta chiara e professionale per l'utente utilizzando questi dati." +
                            "\nNON includere tag [FUNCTION:...] nella risposta." +
                            "\nRICORDA: Le funzioni sono già state eseguite, tu devi solo comunicare i risultati." +
                            "\nFORMATTAZIONE IMPORTANTE:" +
                            "\n- Usa doppio ritorno a capo (\\n\\n) tra ogni elemento di una lista" +
                            "\n- Dopo il titolo '📦 Ordini in sospeso:' vai a capo con \\n+\\n" +
                            "\n- Ogni ordine (WH/...) deve essere su una riga separata con \\n+\\n dopo" +
                            "\n- Esempio formato corretto:" +
                            "\n📦 Ordini in sospeso:\\n\\nWH/OUT/00001 - ...\\n\\nWH/OUT/00002 - ..."}
                    ]

                    final_response = (self._get_gemini_response(config, follow_up_messages) or "").strip()

                    # Rimuovi eventuali tag [FUNCTION:...] dalla risposta finale (doppia sicurezza)
                    if '[FUNCTION:' in final_response:
                        _logger.warning(f"AI ha incluso tag FUNCTION nella risposta finale, li rimuovo: {final_response}")
                        final_response = re.sub(r'\[FUNCTION:[^\]]+\]', '', final_response).strip()

                    # Se la risposta finale è ancora vuota, usa un fallback
                    if not final_response:
                        fallback_lines = []
                        for function_name, parameters, result in executed_calls:
                            fallback_lines.append(f"Risultati {function_name}:")
                            fallback_lines.append(json.dumps(result, indent=2))
                        final_response = "\n".join(fallback_lines) if fallback_lines else "Nessuna informazione disponibile."

            else:
                # Nessuna funzione da eseguire, usa la risposta diretta
                final_response = clean_response if clean_response else ai_response

            final_response = final_response or "Nessuna informazione disponibile."

            # Rimuovi eventuali tag [FUNCTION:...] residui dalla risposta finale (sicurezza)
            try:
                if final_response and '[FUNCTION:' in final_response:
                    final_response = re.sub(r'\[FUNCTION:[^\]]+\]', '', final_response).strip()
            except Exception:
                pass

            # Formatta con HTML (usa la stessa funzione di odoobot_override.py)
            formatted_response = format_html_response(final_response)

            # Invia la risposta nella chat
            self.message_post(
                body=formatted_response,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
                author_id=self.env.ref('base.partner_root').id,
            )
            
        except Exception as e:
            _logger.error(f"Errore generazione risposta AI: {e}")
            error_message = f"Mi dispiace, si è verificato un errore: {str(e)}"
            # Formatta anche gli errori
            formatted_error = format_html_response(error_message)
            self.message_post(
                body=formatted_error,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
                author_id=self.env.ref('base.partner_root').id,
            )
