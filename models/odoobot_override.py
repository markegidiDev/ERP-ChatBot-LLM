from odoo import models, api
from markupsafe import Markup
import logging
import time
import re
import json
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

_logger = logging.getLogger(__name__)

# Rate limiting globale per evitare troppe chiamate
_last_call_time = {}
_MIN_INTERVAL = 2  # Minimo 2 secondi tra una chiamata e l'altra per utente

# Orario standard per le consegne (10:00)
BUSINESS_HOUR = 10


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


def _balanced_json_extract(txt):
    """Estrae un JSON bilanciato da una stringa."""
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


def _parse_iso_duration(dur):
    """
    Parse una durata ISO 8601 semplificata (es: P5D, P1W, PT120H).
    Supporta: PnYnMnWnDTnHnMnS
    """
    m = re.fullmatch(r'P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?', dur, re.I)
    if not m:
        return relativedelta()
    y, mo, w, d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return relativedelta(years=y, months=mo, weeks=w, days=d, hours=h, minutes=mi, seconds=s)


class MailBot(models.AbstractModel):
    _inherit = 'mail.bot'

    def _llm_when_to_datetime(self, user_text):
        """
        Chiede all'AI di normalizzare 'quando' dal testo utente.
        Ritorna un datetime (timezone-aware Europe/Rome) oppure None.
        """
        try:
            ai_chatbot = self.env['discuss.channel']
            config = self.env['ai.config'].get_active_config()

            # Base time nel fuso dell'utente
            from odoo import fields
            base = fields.Datetime.context_timestamp(self, fields.Datetime.now())

            prompt = (
                "Sei un normalizzatore di date/tempi IT.\n"
                f"Oggi (NOW) è: {base.strftime('%Y-%m-%d %H:%M:%S')} Europe/Rome.\n"
                "Dato questo testo utente, estrai SOLO il 'quando'. "
                "Rispondi in una sola riga con un JSON come uno dei seguenti:\n"
                '{ "absolute": "YYYY-MM-DD HH:MM:SS" }\n'
                '{ "relative": "PnYnMnWnDTnHnMnS" }\n'
                "{}\n"
                "Scegli 'absolute' se il testo contiene una data concreta (anche se relativa ma facile da risolvere), "
                "altrimenti 'relative' con durata ISO 8601 equivalente (es: 5 giorni => P5D; 1 settimana => P1W; 120 ore => PT120H). "
                "Non scrivere altro fuori dal JSON."
                "\n\nTESTO UTENTE:\n" + user_text
            )

            resp = ai_chatbot._get_gemini_response(config, [{'role': 'user', 'content': prompt}])
            js = _balanced_json_extract(resp or "") or "{}"
            data = json.loads(js)

            if isinstance(data, dict):
                if data.get('absolute'):
                    # Interpreta come Europe/Rome
                    dt = datetime.strptime(data['absolute'], "%Y-%m-%d %H:%M:%S")
                elif data.get('relative'):
                    dt = base + _parse_iso_duration(data['relative'])
                else:
                    return None

                # Normalizza a orario aziendale standard
                dt = dt.replace(hour=BUSINESS_HOUR, minute=0, second=0, microsecond=0)
                _logger.info(f"✅ [WHEN] Normalized: {user_text[:50]} → {dt.strftime('%Y-%m-%d %H:%M:%S')}")
                return dt

        except Exception as e:
            _logger.warning(f"LLM when normalize failed: {e}", exc_info=True)
        return None

    @api.model
    def _apply_logic(self, record, values, command=False):
        """
        Override del metodo che gestisce le risposte di OdooBot.
        Quando un utente scrive @OdooBot, intercettiamo e usiamo la nostra AI.
        """
        if self.env.context.get('ai_livebot_skip_bot_logic'):
            return super()._apply_logic(record, values, command)

        # non rispondere ai messaggi generati dal bot
        author_id = values.get('author_id')
        if isinstance(author_id, (list, tuple)):
            author_id = author_id[0]
        elif isinstance(author_id, dict):
            author_id = author_id.get('id')

        # Se author_id non è in values, prova a ottenerlo dal contesto o dall'utente corrente
        if not author_id:
            author_id = self.env.user.partner_id.id

        bot_partner_ids = {
            partner.id
            for partner in (
                self.env.ref('base.partner_odoobot', raise_if_not_found=False),
                self.env.ref('base.partner_root', raise_if_not_found=False),
            )
            if partner
        }
        odoobot_id = next(iter(bot_partner_ids), None)

        if author_id and author_id in bot_partner_ids:
            return

        if not odoobot_id:
            _logger.warning("Impossibile determinare il partner di OdooBot, uso comportamento standard")
            return super()._apply_logic(record, values, command)
        
        # Rate limiting
        current_time = time.time()
        user_id = self.env.user.id
        last_time = _last_call_time.get(user_id, 0)
        
        if current_time - last_time < _MIN_INTERVAL:
            _logger.warning(f"Rate limit: utente {user_id} sta chiamando troppo velocemente")
            return
        
        _last_call_time[user_id] = current_time
        
        # Verifica se c'e una configurazione AI attiva
        try:
            config = self.env['ai.config'].search([('active', '=', True)], limit=1)
            if not config:
                # Se non c'e config AI, usa il comportamento standard di OdooBot
                return super()._apply_logic(record, values, command)
        except Exception:
            # Se non c'e config AI, usa il comportamento standard di OdooBot
            return super()._apply_logic(record, values, command)
        
        body = values.get('body', '')
        
        # Se il messaggio e vuoto o troppo corto, usa il comportamento standard
        if not body or len(body.strip()) < 2:
            return super()._apply_logic(record, values, command)
        
       

        # COMANDO SPECIALE: /help - Mostra comandi disponibili
        if body.strip().lower() in ('/help', '/aiuto', '/?'):
            help_message = Markup(  
                "<strong>🤖 Comandi AI Assistant</strong><br/><br/>"
                "<strong>Comandi disponibili:</strong><br/>"
                "• <code>/reset</code> - Resetta la conversazione e riparti da zero<br/>"
                "• <code>/help</code> - Mostra questo messaggio di aiuto<br/><br/>"
                "<strong>Cosa posso fare:</strong><br/>"
                "• 📦 Creare ordini di vendita<br/>"
                "• 🔍 Cercare prodotti e clienti<br/>"
                "• 📊 Visualizzare stock e ordini in sospeso<br/>"
                "• ✏️ Modificare ordini e delivery<br/>"
                "• 👤 Creare nuovi clienti<br/><br/>"
                "<strong>Esempi:</strong><br/>"
                "• <em>Crea ordine per Cliente X: 10 sedie</em><br/>"
                "• <em>Mostrami le consegne in uscita</em><br/>"
                "• <em>Modifica WH/OUT/00015: 5 armadi invece di 10</em><br/>"
                "• <em>Cerca prodotto armadietto grande</em>"
            )
            record.with_context(ai_livebot_skip_bot_logic=True).message_post(
                body=help_message,
                author_id=odoobot_id,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )
            return
        
        # COMANDO SPECIALE: /reset - Resetta la conversazione
        if body.strip().lower() in ('/reset', '/restart', '/clear', '/nuovo'):
            try:
                # Cancella i messaggi nel canale (opzionale - mantieni storico ma segnala reset)
                reset_message = Markup(
                    "<strong>🔄 Conversazione Resettata</strong><br/><br/>"
                    "Ho cancellato lo storico conversazionale. Ripartiamo da zero!<br/><br/>"
                    "Cosa posso fare per te?"
                )
                record.with_context(ai_livebot_skip_bot_logic=True).message_post(
                    body=reset_message,
                    author_id=odoobot_id,
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment',
                )
                
                # Aggiungi marker di reset (usato da _build_conversation_history)
                record.with_context(ai_livebot_skip_bot_logic=True).message_post(
                    body="[SYSTEM_RESET]",
                    author_id=odoobot_id,
                    message_type='notification',
                    subtype_xmlid='mail.mt_note',
                )
                _logger.info(f"✅ Conversazione resettata per canale {record.id} da utente {self.env.user.name}")
                return
            except Exception as e:
                _logger.error(f"Errore durante reset conversazione: {e}")
                record.with_context(ai_livebot_skip_bot_logic=True).message_post(
                    body=f"⚠️ Errore durante il reset: {str(e)}",
                    author_id=odoobot_id,
                    message_type='comment',
                )
                return
        
        # Ottieni la risposta dall'AI invece che da OdooBot
        try:
            ai_response = self._get_ai_response(body, record)
            
            if ai_response:
                # Invia la risposta AI invece della risposta standard di OdooBot
                record.with_context(ai_livebot_skip_bot_logic=True).message_post(
                    body=ai_response,
                    author_id=odoobot_id,
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment',
                )
                return  # Non eseguire la logica standard
        except Exception as e:
            _logger.error(f"Errore nell'ottenere risposta AI: {e}")

            record.with_context(ai_livebot_skip_bot_logic=True).message_post(
                body=f"Mi dispiace, si e verificato un errore: {str(e)}",
                author_id=odoobot_id,
                message_type='comment',
            )
            return

        #  fallback alla logica sta
        return super()._apply_logic(record, values, command)
    
    def _get_ai_response(self, user_message, channel):
        """Ottiene una risposta dall'AI"""
        try:
            config = self.env['ai.config'].get_active_config()
            
            # STEP 1: Check for pending sales order confirmation
            pending_so_json = self._check_pending_sales_order(channel, user_message)
            if pending_so_json:
                # User confirmed, execute the create_sales_order
                _logger.info(f"Utente ha confermato ordine pendente: {pending_so_json}")
                
                # Esegui direttamente warehouse_ops bypassando il gate
                warehouse_ops = self.env['warehouse.operations']
                
                # Converti scheduled_date da stringa a datetime se necessario
                if 'scheduled_date' in pending_so_json and isinstance(pending_so_json['scheduled_date'], str):
                    try:
                        from datetime import datetime
                        scheduled_str = pending_so_json['scheduled_date']
                        if ' ' in scheduled_str:
                            pending_so_json['scheduled_date'] = datetime.strptime(scheduled_str, "%Y-%m-%d %H:%M:%S")
                        else:
                            pending_so_json['scheduled_date'] = datetime.strptime(scheduled_str, "%Y-%m-%d")
                    except Exception as e:
                        _logger.warning(f"Errore conversione scheduled_date: {e}")
                        pending_so_json.pop('scheduled_date', None)
                
                # ESEGUI LA CREATE BYPASSANDO IL GATE
                result = warehouse_ops.create_sales_order(**pending_so_json)
                
                # Format the response
                lines = []
                if isinstance(result, dict) and result.get('error'):
                    lines.append(f"⚠️ Errore: {result.get('error')}")
                    if result.get('details'):
                        lines.append(result.get('details'))
                else:
                    order_name = result.get('sale_order_name') or result.get('order_name')
                    if order_name:
                        lines.append(f"✅ Ordine creato: {order_name}")
                    order_id = result.get('sale_order_id') or result.get('order_id')
                    if order_id:
                        lines.append(f"ID interno: {order_id}")
                    
                    # Stato con mapping
                    state = result.get('state', 'N/A')
                    state_map = {'draft': 'Bozza', 'sent': 'Inviato', 'sale': 'Confermato', 'done': 'Evaso'}
                    state_display = state_map.get(state, state)
                    lines.append(f"Stato: {state_display}")
                    
                    pickings = result.get('pickings', [])
                    if pickings:
                        lines.append("\nConsegne generate:")
                        for p in pickings:
                            lines.append(f"  • {p.get('picking_name')} - {p.get('scheduled_date', 'N/A')}")
                    lines.append(f"\nTotale: €{result.get('amount_total', 0):.2f}")
                
                return format_html_response("\n\n".join(lines) if lines else "Operazione completata.")
            
            # STEP 2: Check if user cancelled pending order
            if self._is_cancellation(user_message) and self._has_pending_marker(channel):
                return format_html_response("✅ Ordine annullato.")
            
            # Prepara il contesto delle funzioni disponibili
            functions_context = self._get_functions_context()
            
            # Recupera lo storico conversazione dal canale (ultimi 10 messaggi)
            messages = self._build_conversation_history(channel, user_message, functions_context)
            
            _logger.info(f"Costruiti {len(messages)} messaggi di contesto per AI")
            
            # Ottieni risposta dall'AI 
            ai_chatbot = self.env['discuss.channel']
            ai_response = ai_chatbot._get_gemini_response(config, messages)
            
            # Controlla se l'AI vuole eseguire una o più funzioni
            function_calls, clean_response = ai_chatbot._parse_ai_function_calls(ai_response)

            # Retry parsing se l'AI ha messo i tag in blocchi di codice/backticks
            if not function_calls and '[FUNCTION:' in (ai_response or ''):
                try:
                    cleaned_try = re.sub(r'```.*?```', '', ai_response, flags=re.S)
                    cleaned_try = cleaned_try.replace('`', '').strip()
                    if cleaned_try != ai_response:
                        _logger.info('Retry parsing FUNCTION tags after cleaning AI response (odoobot)')
                        function_calls, clean_response = ai_chatbot._parse_ai_function_calls(cleaned_try)
                        if function_calls:
                            ai_response = cleaned_try
                except Exception:
                    pass

            # Fallback: se ancora niente ma c'è un tag [FUNCTION:nome] senza parametri
            if not function_calls and '[FUNCTION:' in (ai_response or ''):
                bare = re.findall(r'\[(?:FUNCTION|Function|function):\s*([A-Za-z0-9_]+)\s*\]', ai_response)
                if bare:
                    function_calls = [(name.strip(), {}) for name in bare]
                    clean_response = re.sub(r'\[(?:FUNCTION|Function|function):[^\]]+\]', '', ai_response).strip()
                    _logger.info(f"✅ Fallback bare FUNCTION (odoobot): created {len(function_calls)} call(s) with empty params.")

            # Se ancora nessuna funzione ma la risposta contiene frammenti come "|... ]",
            # chiedi all'AI di restituire SOLO il tag completo e riprova.
            if not function_calls and (ai_response and '|' in ai_response and ']' in ai_response):
                try:
                    follow_up_messages = messages + [
                        {'role': 'assistant', 'content': ai_response},
                        {'role': 'user', 'content': (
                            "Hai restituito un tag funzione troncato. Restituisci SOLO il tag completo in una riga, "
                            "senza alcun testo prima o dopo. Esempio: "
                            "[FUNCTION:create_sales_order|partner_name:CLIENTE|order_lines:[{\"product_id\":ID,\"quantity\":QTY}]|confirm:true]. "
                            "Se serve cercare il prodotto, restituisci prima [FUNCTION:search_products|search_term:NOME|limit:5]."
                        )},
                    ]
                    ai_response_fixed = ai_chatbot._get_gemini_response(config, follow_up_messages)
                    function_calls, clean_response = ai_chatbot._parse_ai_function_calls(ai_response_fixed)
                    if function_calls:
                        ai_response = ai_response_fixed
                except Exception:
                    pass
            
            if function_calls:
                function_name, parameters = function_calls[0]
                _logger.info(f"AI richiede funzione: {function_name} con params: {parameters}")

                # Se l'utente ha espresso una data relativa (es. "tra 5 giorni"),
                # calcola scheduled_date lato server usando AI normalizer.
                exec_params = dict(parameters) if isinstance(parameters, dict) else {}
                if function_name == 'create_sales_order':
                    dt = self._llm_when_to_datetime(user_message)
                    if dt:
                        exec_params['scheduled_date'] = dt.strftime("%Y-%m-%d %H:%M:%S")
                        _logger.info(f"[WHEN] scheduled_date from LLM-normalized: {exec_params['scheduled_date']}")

                result = ai_chatbot._execute_function(function_name, exec_params)
                
                # ✅ Se create_sales_order richiede conferma, restituisci SOLO il messaggio formattato
                if function_name == 'create_sales_order' and isinstance(result, dict) and result.get('requires_confirmation'):
                    dt = self._llm_when_to_datetime(user_message)
                    if dt:
                        sd = dt.strftime("%Y-%m-%d %H:%M:%S")
                        # allinea sia i parametri pendenti che il testo del messaggio
                        if 'pending_params' in result:
                            result['pending_params']['scheduled_date'] = sd
                        if 'summary' in result:
                            result['summary']['scheduled_date'] = sd
                        # Aggiorna anche il messaggio formattato con regex robusta
                        if 'message' in result:
                            result['message'] = re.sub(
                                r'(Data consegna:\s*)(\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2}:\d{2})?)',
                                r'\g<1>' + sd,
                                result['message']
                            )
                        _logger.info(f"✅ Data riepilogo allineata a: {sd}")
                    
                    # 🚨 FIX: Restituisci SOLO il messaggio, NON tutto il dict
                    _logger.info("✅ Richiesta conferma - restituisco SOLO il campo 'message'")
                    return format_html_response(result.get('message', 'Confermi?'))



                # Helper per formattare prezzi
                def _fmt_price(val):
                    return f"€{float(val):,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
                
                # Formattazione server-side per search_products
                if function_name == 'search_products' and isinstance(result, list):
                    lines = [f"🔍 Prodotti trovati ({len(result)}):"]
                    lines.append("")
                    
                    for p in result:
                        qty = p.get('qty_available') or 0
                        availability = f"{int(qty)} unità" if qty > 0 else "Esaurito ⚠️"
                        price = p.get('list_price', None)
                        price_txt = _fmt_price(price) if isinstance(price, (int, float)) else "Prezzo da definire"
                        lines.append(f"• {p['name']} (ID: {p['id']}) - {price_txt} - {availability}")
                    
                    return format_html_response("\n\n".join(lines))
                
                # Formattazione server-side per get_sales_overview
                if function_name == 'get_sales_overview' and isinstance(result, dict):
                    lines = [f"📊 Panoramica Vendite - Periodo: {result.get('period', 'N/A').upper()}"]
                    lines.append("")
                    lines.append(f"🔢 Totale ordini: {result.get('total_orders', 0)}")
                    lines.append(f"💰 Fatturato totale: {_fmt_price(result.get('total_revenue', 0))}")
                    lines.append(f"📈 Valore medio ordine: {_fmt_price(result.get('avg_order_value', 0))}")
                    lines.append("")
                    
                    # Stati ordini
                    states_map = {'draft': 'Bozza', 'sent': 'Inviato', 'sale': 'Confermato', 'done': 'Evaso', 'cancel': 'Annullato'}
                    if result.get('orders_by_state'):
                        lines.append("📋 Ordini per stato:")
                        for state, count in result.get('orders_by_state', {}).items():
                            state_txt = states_map.get(state, state)
                            lines.append(f"  • {state_txt}: {count}")
                        lines.append("")
                    
                    # Ultimi ordini
                    orders = result.get('orders', [])
                    if orders:
                        lines.append(f"📦 Ultimi {len(orders)} ordini:")
                        lines.append("")
                        for o in orders[:10]:  # Mostra max 10
                            state_txt = states_map.get(o.get('state'), o.get('state'))
                            lines.append(f"• {o.get('name')} - {o.get('partner')} - {_fmt_price(o.get('amount_total', 0))} - {state_txt}")
                    
                    return format_html_response("\n\n".join(lines))
                
                # Formattazione server-side per get_sales_order_details
                if function_name == 'get_sales_order_details' and isinstance(result, dict) and not result.get('error'):
                    lines = [f"📄 Dettagli Ordine: {result.get('order_name')}"]
                    lines.append("")
                    lines.append(f"👤 Cliente: {result.get('partner')}")
                    if result.get('partner_email'):
                        lines.append(f"📧 Email: {result.get('partner_email')}")
                    if result.get('partner_phone'):
                        lines.append(f"📞 Tel: {result.get('partner_phone')}")
                    lines.append(f"📅 Data ordine: {result.get('date_order', 'N/A')}")
                    lines.append(f"📊 Stato: {result.get('state_display', result.get('state'))}")
                    lines.append(f"💰 Totale: {_fmt_price(result.get('amount_total', 0))}")
                    
                    # --- Delivery status robusto (nessuna KeyError) ---
                    status = result.get('delivery_status') or result.get('delivery_status_computed')
                    if status:
                        labels = {
                            'nothing_to_deliver': 'Nulla da consegnare',
                            'not_delivered': 'Non consegnato',
                            'partially_delivered': 'Parzialmente consegnato',
                            'fully_delivered': 'Consegnato',
                        }
                        lines.append(f"🚚 Consegna: {labels.get(status, status)}")
                    
                    lines.append("")
                    
                    # Righe ordine
                    order_lines = result.get('order_lines', [])
                    if order_lines:
                        lines.append(f"📦 Prodotti ({len(order_lines)}):")
                        lines.append("")
                        for line in order_lines:
                            qty = line.get('quantity', 0)
                            price = _fmt_price(line.get('price_unit', 0))
                            subtotal = _fmt_price(line.get('subtotal', 0))
                            lines.append(f"• {line.get('product')} - Qtà: {int(qty)} - Prezzo: {price} - Subtotale: {subtotal}")
                    
                    # Delivery collegati
                    pickings = result.get('pickings', [])
                    if pickings:
                        lines.append("")
                        lines.append(f"🚚 Consegne ({len(pickings)}):")
                        for p in pickings:
                            lines.append(f"  • {p.get('picking_name')} - Stato: {p.get('state_display', p.get('state'))}")
                    
                    return format_html_response("\n\n".join(lines))
                
                # Formattazione server-side per get_top_customers
                if function_name == 'get_top_customers' and isinstance(result, dict):
                    lines = [f"🏆 Top Clienti - Periodo: {result.get('period', 'N/A').upper()}"]
                    lines.append("")
                    
                    customers = result.get('top_customers', [])
                    if customers:
                        for idx, c in enumerate(customers, 1):
                            lines.append(f"{idx}. {c.get('partner')} - Ordini: {c.get('total_orders')} - Fatturato: {_fmt_price(c.get('total_revenue', 0))} - Media: {_fmt_price(c.get('avg_order_value', 0))}")
                    else:
                        lines.append("Nessun cliente trovato nel periodo")
                    
                    return format_html_response("\n\n".join(lines))
                
                # Formattazione server-side per get_products_sales_stats
                if function_name == 'get_products_sales_stats' and isinstance(result, dict):
                    lines = [f"📊 Prodotti Più Venduti - Periodo: {result.get('period', 'N/A').upper()}"]
                    lines.append("")
                    
                    products = result.get('top_products', [])
                    if products:
                        for idx, p in enumerate(products[:15], 1):  # Max 15
                            qty = int(p.get('total_qty_sold', 0))
                            revenue = _fmt_price(p.get('total_revenue', 0))
                            avg = _fmt_price(p.get('avg_price', 0))
                            lines.append(f"{idx}. {p.get('product')} - Venduti: {qty} - Fatturato: {revenue} - Prezzo medio: {avg}")
                    else:
                        lines.append("Nessun prodotto venduto nel periodo")
                    
                    return format_html_response("\n\n".join(lines))

                # Se è una funzione mutante, compone una risposta diretta senza chiedere all'AI
                mutating_fns = {'create_sales_order', 'create_partner', 'create_delivery_order', 'validate_delivery', 'update_sales_order', 'update_delivery', 'process_delivery_decision'}
                
                # Gestione speciale per validate_delivery che richiede decisione
                if function_name == 'validate_delivery' and isinstance(result, dict) and result.get('requires_decision'):
                    # Mini-wizard testuale: chiedi all'utente come procedere
                    lines = [
                        f"⚠️ {result.get('message')}",
                        "",
                        "Rispondi con:",
                        "• 1 o 'backorder' → Evadi ORA e CREA Backorder",
                        "• 2 o 'no backorder' → Evadi ORA SENZA Backorder (scarta residuo)",
                        "• 3 o 'immediato' → Trasferimento immediato (imposta done = demand)",
                    ]
                    if result.get('details'):
                        lines.append("")
                        lines.append("Dettagli riserva:")
                        for det in result['details']:
                            lines.append(f"  • {det.get('product')}: riservato {det.get('reserved')} su {det.get('demand')}")
                    return format_html_response("\n".join(lines))
                
                if function_name in mutating_fns:
                    lines = []
                    if isinstance(result, dict) and result.get('error'):
                        lines.append(f"⚠️ Errore eseguendo {function_name}: {result.get('error')}")
                        if result.get('details'):
                            lines.append(result.get('details'))
                    else:
                        if function_name == 'create_sales_order':
                            order_name = result.get('sale_order_name') or result.get('order_name') or result.get('name') or result.get('display_name')
                            order_id = result.get('sale_order_id') or result.get('order_id') or result.get('id')
                            if order_name:
                                lines.append(f"✅ Ordine creato: {order_name}")
                            if order_id:
                                lines.append(f"ID interno: {order_id}")
                            pickings = result.get('pickings') or result.get('picking') or result.get('picking_ids') or result.get('picking_id')
                            if pickings:
                                try:
                                    lines.append("Consegne generate:")
                                    lines.append(json.dumps(pickings, indent=2))
                                except Exception:
                                    lines.append(str(pickings))
                            try:
                                lines.append("Dettagli ordine:")
                                lines.append(json.dumps(result, indent=2))
                            except Exception:
                                pass
                        elif function_name == 'update_sales_order':
                            order_name = result.get('order_name')
                            if order_name:
                                lines.append(f"✅ Ordine {order_name} aggiornato")
                            if result.get('updated_lines'):
                                lines.append("Righe modificate:")
                                for upd in result['updated_lines']:
                                    lines.append(f"  • {upd['product']}: {upd['old_quantity']} → {upd['new_quantity']}")
                            if result.get('added_lines'):
                                lines.append("Righe aggiunte:")
                                for add in result['added_lines']:
                                    lines.append(f"  • {add['product']}: {add['quantity']} pz")
                            if result.get('deleted_lines'):
                                lines.append(f"Righe eliminate: {', '.join(result['deleted_lines'])}")
                            if result.get('amount_total'):
                                lines.append(f"Totale ordine: €{result['amount_total']}")
                        elif function_name == 'update_delivery':
                            picking_name = result.get('picking_name')
                            if picking_name:
                                lines.append(f"✅ Delivery {picking_name} aggiornato")
                            if result.get('updated_moves'):
                                lines.append("Movimenti modificati:")
                                for upd in result['updated_moves']:
                                    lines.append(f"  • {upd['product']}: {upd['old_quantity']} → {upd['new_quantity']}")
                            if result.get('added_moves'):
                                lines.append("Movimenti aggiunti:")
                                for add in result['added_moves']:
                                    lines.append(f"  • {add['product']}: {add['quantity']} pz")
                            if result.get('deleted_moves'):
                                lines.append(f"Movimenti eliminati: {', '.join(result['deleted_moves'])}")
                        elif function_name == 'process_delivery_decision':
                            lines.append(f"✅ {result.get('message')}")
                            lines.append(f"Delivery: {result.get('picking_name')} - Stato: {result.get('state', 'N/D')}")
                            bos = result.get('created_backorders') or []
                            if bos:
                                lines.append("")
                                lines.append("Backorder creati:")
                                for bo in bos:
                                    lines.append(f"  • {bo['name']} - Stato: {bo['state']}")
                        else:
                            lines.append(f"✅ {function_name} eseguita con successo")
                    final_response = "\n\n".join(lines) if lines else "Operazione completata."

                    # Rimuovi eventuali tag FUNCTION residui, per sicurezza
                    final_response = re.sub(r'\[FUNCTION:[^\]]+\]', '', final_response).strip()
                    
                    # Formatta con HTML
                    return format_html_response(final_response)

                # Altrimenti (funzioni di sola lettura), chiedi all'AI di formattare la risposta
                # Se abbiamo appena eseguito search_products, l'utente probabilmente vuole creare un ordine
                # Quindi chiediamo esplicitamente all'AI di generare create_sales_order
                if function_name == 'search_products' and isinstance(result, list) and len(result) > 0:
                    # Estrai il product_id dal primo risultato
                    product_info = result[0]
                    follow_up_messages = messages + [
                        {'role': 'assistant', 'content': f"[FUNCTION:search_products|search_term:{parameters.get('search_term')}|limit:{parameters.get('limit', 5)}]"},
                        {'role': 'user', 'content': (
                            f"Risultato ricerca prodotti: {json.dumps(result, indent=2)}\n\n"
                            f"IMPORTANTE: Ora devi creare l'ordine. Rispondi con il tag completo per create_sales_order:\n"
                            f"[FUNCTION:create_sales_order|partner_name:NOME_CLIENTE|order_lines:[{{\"product_id\":{product_info.get('id')},\"quantity\":QUANTITA}}]|confirm:true]\n\n"
                            f"Sostituisci NOME_CLIENTE e QUANTITA con i valori corretti dalla richiesta originale dell'utente."
                        )}
                    ]
                else:
                    follow_up_messages = messages + [
                        {'role': 'assistant', 'content': clean_response if clean_response else ai_response},
                        {'role': 'user', 'content': f"Risultato: {json.dumps(result)}\n\nRispondi in modo chiaro SENZA tag [FUNCTION:...]"}
                    ]
                final_response = ai_chatbot._get_gemini_response(config, follow_up_messages)
                # Sicurezza: rimuovi tag se l'AI li include
                try:
                    if final_response and '[FUNCTION:' in final_response:
                        # Se la risposta contiene altri tag FUNCTION, eseguili ricorsivamente
                        next_calls, next_clean = ai_chatbot._parse_ai_function_calls(final_response)
                        if next_calls:
                            _logger.info(f"Trovate {len(next_calls)} funzioni aggiuntive nella risposta follow-up")
                            for next_fn, next_params in next_calls:
                                _logger.info(f"Eseguo funzione aggiuntiva: {next_fn} con params: {next_params}")
                                next_result = ai_chatbot._execute_function(next_fn, next_params)
                                
                                # Se è create_sales_order, formatta e restituisci
                                if next_fn in mutating_fns:
                                    lines = []
                                    if isinstance(next_result, dict) and next_result.get('error'):
                                        lines.append(f"⚠️ Errore: {next_result.get('error')}")
                                        if next_result.get('details'):
                                            lines.append(next_result.get('details'))
                                    else:
                                        if next_fn == 'create_sales_order':
                                            order_name = next_result.get('sale_order_name') or next_result.get('order_name') or next_result.get('name')
                                            if order_name:
                                                lines.append(f"✅ Ordine creato: {order_name}")
                                            order_id = next_result.get('sale_order_id') or next_result.get('order_id') or next_result.get('id')
                                            if order_id:
                                                lines.append(f"ID: {order_id}")
                                            try:
                                                lines.append(json.dumps(next_result, indent=2))
                                            except Exception:
                                                pass
                                        else:
                                            lines.append(f"✅ {next_fn} eseguita")
                                    formatted_response = "\n\n".join(lines) if lines else "Operazione completata."
                                    return format_html_response(formatted_response)
                        
                        # Rimuovi i tag dalla risposta finale
                        final_response = re.sub(r'\[FUNCTION:[^\]]+\]', '', final_response).strip()
                except Exception as e:
                    _logger.warning(f"Errore parsing funzioni aggiuntive: {e}")
                
                # Formatta con HTML
                return format_html_response(final_response)
            
            # Nessuna funzione da eseguire
            # ✅ FIX SPAZIATURE: Se clean_response è vuoto o ha perso formattazione, usa ai_response originale
            final_response = clean_response if clean_response else ai_response
            
            # Se clean_response è molto più corto dell'originale (ha perso contenuto/formattazione)
            if ai_response and clean_response and len(clean_response) < len(ai_response) * 0.7:
                _logger.warning(f"⚠️ clean_response ({len(clean_response)} char) molto più corto di ai_response ({len(ai_response)} char) - uso originale")
                final_response = ai_response
            
            return format_html_response(final_response)
            
        except Exception as e:
            _logger.error(f"Errore risposta AI: {e}")
            return f"Mi dispiace, si e verificato un errore: {str(e)}"
    
    def _check_pending_sales_order(self, channel, user_message):
        """
        Controlla se c'è un ordine pendente e se l'utente ha confermato.
        Restituisce il JSON dei parametri se confermato, altrimenti None.
        """
        # Check if user confirmed
        _logger.info(f"🔍 Checking confirmation for message: {user_message}")
        if not re.search(r'\b(S[IÌI]|CONFERMO|OK\s*VAI|PERFETTO)\b', user_message, re.I):
            _logger.info("❌ No confirmation keyword found")
            return None
        
        _logger.info("✅ Confirmation keyword detected!")
        
        # Look for [PENDING_SO] marker in last bot message
        try:
            from odoo.addons.ai_livebot.models.ai_chatbot import PENDING_SO_MARKER
            
            bot_partner_ids = {
                partner.id
                for partner in (
                    self.env.ref('base.partner_odoobot', raise_if_not_found=False),
                    self.env.ref('base.partner_root', raise_if_not_found=False),
                )
                if partner
            }
            
            # Get last bot message
            last_bot_msg = self.env['mail.message'].search([
                ('model', '=', channel._name),
                ('res_id', '=', channel.id),
                ('author_id', 'in', list(bot_partner_ids)),
                ('message_type', '=', 'comment'),
            ], order='date desc', limit=1)
            
            if last_bot_msg and last_bot_msg.body:
                body_text = re.sub(r'<[^>]+>', '', last_bot_msg.body or '').strip()
                _logger.info(f"📄 Last bot message (first 200 chars): {body_text[:200]}")
                
                # Look for marker - usa parser a contatore di graffe per JSON annidati
                text = body_text
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
                            _logger.info(f"✅ Found marker with JSON: {json_str}")
                            parsed = json.loads(json_str)
                            _logger.info(f"✅ Parsed params: {parsed}")
                            return parsed
                _logger.warning(f"❌ Marker {PENDING_SO_MARKER} not found or JSON not balanced")
            else:
                _logger.warning("❌ No last bot message found")
        except Exception as e:
            _logger.error(f"❌ Errore checking pending SO: {e}", exc_info=True)
        
        return None
    
    def _is_cancellation(self, user_message):
        """
        Usa l'LLM per capire se l'utente vuole annullare l'ordine.
        Restituisce True solo se c'è una CHIARA intenzione di annullamento.
        """
        try:
            ai_chatbot = self.env['discuss.channel']
            config = self.env['ai.config'].get_active_config()
            
            prompt = (
                "Sei un classificatore di intenti. "
                "L'utente ha un ordine in sospeso che deve confermare. "
                "Analizza questo messaggio e rispondi SOLO con 'YES' o 'NO'.\n\n"
                "Rispondi 'YES' se l'utente vuole CHIARAMENTE annullare/cancellare l'ordine.\n"
                "Rispondi 'NO' se l'utente vuole modificare, cambiare data, o continua la conversazione.\n\n"
                "Esempi:\n"
                "- 'no grazie' → YES\n"
                "- 'annulla tutto' → YES\n"
                "- 'no, aspetta' → YES\n"
                "- 'no scherzo, voglio il 30' → NO (vuole modificare)\n"
                "- 'no, lo voglio tra 5 giorni' → NO (vuole modificare)\n"
                "- 'cambia la data' → NO (vuole modificare)\n\n"
                f"MESSAGGIO UTENTE: {user_message}\n\n"
                "RISPONDI SOLO: YES o NO"
            )
            
            response = ai_chatbot._get_gemini_response(config, [{'role': 'user', 'content': prompt}])
            response_clean = (response or '').strip().upper()
            
            is_cancel = 'YES' in response_clean
            _logger.info(f"🤖 LLM cancellation check: '{user_message[:50]}' → {response_clean} → {'CANCEL' if is_cancel else 'KEEP'}")
            
            return is_cancel
            
        except Exception as e:
            _logger.error(f"Errore LLM cancellation check: {e}", exc_info=True)
            # Fallback sicuro: NON annullare in caso di errore
            return False
    
    def _has_pending_marker(self, channel):
        """Check if there's a pending marker in recent messages"""
        try:
            from odoo.addons.ai_livebot.models.ai_chatbot import PENDING_SO_MARKER
            
            bot_partner_ids = {
                partner.id
                for partner in (
                    self.env.ref('base.partner_odoobot', raise_if_not_found=False),
                    self.env.ref('base.partner_root', raise_if_not_found=False),
                )
                if partner
            }
            
            recent_msg = self.env['mail.message'].search([
                ('model', '=', channel._name),
                ('res_id', '=', channel.id),
                ('author_id', 'in', list(bot_partner_ids)),
                ('message_type', '=', 'comment'),
            ], order='date desc', limit=3)
            
            for msg in recent_msg:
                body_text = re.sub(r'<[^>]+>', '', msg.body or '').strip()
                if PENDING_SO_MARKER in body_text:
                    return True
        except Exception:
            pass
        
        return False
    
    def _get_functions_context(self):
        """Costruisce il contesto delle funzioni disponibili"""
        ai_chatbot = self.env['discuss.channel']
        functions = ai_chatbot._get_available_functions()
        
        context = "\n\nFUNZIONI DISPONIBILI:\n"
        for func_name, func_info in functions.items():
            context += f"- {func_name}: {func_info['description']}\n"
        
        context += "\nPer usare una funzione, rispondi con: [FUNCTION:nome_funzione|param1:value1|param2:value2]"
        return context
    
    def _build_conversation_history(self, channel, current_message, functions_context, max_messages=10):
        """
        Costruisce lo storico della conversazione dal canale.
        Recupera gli ultimi N messaggi e li formatta per Gemini API.
        
        Args:
            channel: Il record discuss.channel o mail.channel
            current_message: Il messaggio corrente dell'utente
            functions_context: Contesto delle funzioni disponibili
            max_messages: Numero massimo di messaggi da includere nello storico
            
        Returns:
            Lista di dict con formato {'role': 'user'|'assistant', 'content': 'testo'}
        """
        messages = []
        
        try:
            # Ottieni partner_id di OdooBot
            bot_partner_ids = {
                partner.id
                for partner in (
                    self.env.ref('base.partner_odoobot', raise_if_not_found=False),
                    self.env.ref('base.partner_root', raise_if_not_found=False),
                )
                if partner
            }
            
            # Ignora messaggi più vecchi di X ore (default: 2 ore)
            from datetime import datetime, timedelta
            cutoff_time = datetime.now() - timedelta(hours=2)
            
            # Recupera messaggi dal canale (ordinati per data, più recenti prima)
            # Usa il modello mail.message per ottenere i messaggi
            channel_messages = self.env['mail.message'].search([
                ('model', '=', channel._name),
                ('res_id', '=', channel.id),
                ('message_type', 'in', ['comment', 'notification']),
                ('date', '>=', cutoff_time),  # Solo messaggi recenti
            ], order='date desc', limit=max_messages)
            
            # Inverti l'ordine per avere i messaggi dal più vecchio al più recente
            channel_messages = channel_messages.sorted(key=lambda m: m.date)
            
            # Cerca marker di reset [SYSTEM_RESET] - ignora tutto prima di esso
            reset_index = -1
            for idx, msg in enumerate(channel_messages):
                if '[SYSTEM_RESET]' in (msg.body or ''):
                    reset_index = idx
                    _logger.info(f"Trovato marker reset all'indice {idx} - ignoro messaggi precedenti")
                    break
            
            # Se trovato reset, prendi solo messaggi DOPO di esso
            if reset_index >= 0:
                channel_messages = channel_messages[reset_index + 1:]
            
            # Costruisci lo storico
            for msg in channel_messages:
                # Estrai il testo pulito (rimuovi HTML)
                body_text = re.sub(r'<[^>]+>', '', msg.body or '').strip()
                
                # Salta messaggi di sistema (marker reset, notifiche)
                if '[SYSTEM_RESET]' in body_text or msg.message_type == 'notification':
                    continue
                
                if not body_text or len(body_text) < 2:
                    continue
                
                # Determina il ruolo
                if msg.author_id.id in bot_partner_ids:
                    role = 'assistant'
                else:
                    role = 'user'
                
                messages.append({
                    'role': role,
                    'content': body_text
                })
            
            # Limita a max_messages (rimuovi i più vecchi se necessario)
            if len(messages) > max_messages:
                messages = messages[-max_messages:]
            
        except Exception as e:
            _logger.warning(f"Errore recupero storico conversazione: {e}")
            # Fallback: usa solo il messaggio corrente
        
        # Aggiungi contesto temporale per l'AI
        from odoo import fields
        now_local = fields.Datetime.context_timestamp(self, fields.Datetime.now())
        messages.append({
            'role': 'user',
            'content': f"[CONTEXT] TODAY={now_local.strftime('%Y-%m-%d %H:%M:%S')} TZ=Europe/Rome"
        })
        
        # Aggiungi il messaggio corrente dell'utente
        messages.append({
            'role': 'user',
            'content': current_message
        })
        
        # Se non abbiamo storico, assicurati che ci sia almeno il messaggio corrente
        if not messages:
            messages = [{
                'role': 'user',
                'content': f"{current_message}\n\n{functions_context}"
            }]
        
        return messages
