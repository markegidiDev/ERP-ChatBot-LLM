# AI LiveBot - Warehouse Assistant 🤖📦

Modulo Odoo 18 con assistente AI integrato per gestione magazzino e ordini tramite linguaggio naturale.

---

![Odoo](https://img.shields.io/badge/Odoo-18.0-714B67)
![Python](https://img.shields.io/badge/Python-3.10+-blue)
![AI](https://img.shields.io/badge/AI-Gemini%20%7C%20OpenRouter-orange)
![License](https://img.shields.io/badge/license-LGPL--3-green)

---

## 🧠 Panoramica

**AI LiveBot** è un modulo Odoo che estende il sistema di chat nativo con capacità di intelligenza artificiale, permettendo agli operatori di magazzino e venditori di gestire ordini, verificare disponibilità e creare documenti usando il linguaggio naturale.

Invece di navigare menu complessi, gli utenti possono semplicemente chiedere:
- _"Controlla la disponibilità di Cestino Rosso"_
- _"Crea un ordine di vendita per 10 unità di Sedia Ergonomica per il cliente ACME"_
- _"Valida la consegna WH/OUT/00123"_
- _"Mostra tutti i prodotti con giacenza inferiore a 5"_

Il sistema usa **Google Gemini** o **OpenRouter** come LLM backend per interpretare le richieste e le traduce automaticamente in operazioni Odoo.

---

## ✨ Funzionalità Principali

### 🔍 **Ricerca Prodotti Intelligente**
- Ricerca fuzzy multi-pattern con normalizzazione automatica
- Match esatto, parziale e per parole chiave
- Supporto plurali, articoli, case-insensitive

### 📦 **Gestione Magazzino**
- Verifica disponibilità prodotti in tempo reale
- Controllo giacenze, incoming/outgoing qty
- Ricerca prodotti con filtri su stock e tipo

### 🛒 **Gestione Ordini di Vendita**
- Creazione ordini di vendita via chat con conferma utente
- Validazione automatica disponibilità prodotti
- Suggerimenti quantità alternative se stock insufficiente
- Supporto multi-riga con prodotti e quantità

### 🚚 **Validazione Consegne**
- Valida delivery orders direttamente da chat
- Verifica stato e dettagli picking (WH/OUT/xxxxx)
- Aggiornamento automatico stato consegne

### ⚙️ **Configurazione AI Flessibile**
- Supporto multipli provider: **Google Gemini** e **OpenRouter**
- Configurazione modelli, temperatura, max_tokens
- System prompt personalizzabile
- Validazione automatica chiavi API con messaggi in italiano
- Sistema single-active: solo una configurazione attiva alla volta

---

## 🏗️ Architettura

```
ai_livebot/
├── models/
│   ├── ai_config.py          # Configurazione LLM con validazione
│   ├── ai_chatbot.py         # Logica chat e orchestrazione LLM
│   ├── warehouse_operations.py # Operazioni magazzino e ricerca prodotti
│   └── odoobot_override.py   # Override risposta OdooBot standard
├── views/
│   └── ai_config_views.xml   # UI configurazione AI
├── controllers/
│   └── main.py               # API endpoints (se necessari)
└── security/
    └── ir.model.access.csv   # Permessi accesso modelli
```

### 🔄 Flusso di Lavoro

1. **Utente** invia messaggio nella chat Odoo
2. **OdooBot Override** intercetta messaggio e chiama `ai_chatbot.py`
3. **AI Chatbot** preleva configurazione attiva da `ai.config`
4. **Normalizzazione** (opzionale): LLM normalizza termini di ricerca prodotti
5. **LLM Call**: Gemini/OpenRouter interpreta la richiesta utente
6. **Tool Execution**: System esegue `search_products`, `get_stock_info`, `create_sales_order`, etc.
7. **Response Formatting**: Converte output in HTML formattato per chat
8. **Utente** riceve risposta strutturata con checkmark, emoji, codici evidenziati

---

## 📦 Installazione

### Prerequisiti

- Odoo 18.0
- Python 3.10+
- Moduli Odoo: `base`, `mail`, `stock`, `sale_management`

### Passaggi

1. **Clona il repository nella directory addons di Odoo:**
   ```bash
   cd /path/to/odoo/addons
   git clone https://github.com/markegidiDev/ERP-ChatBot-LLM.git ai_livebot
   ```

2. **Aggiorna lista app Odoo:**
   - Attiva modalità sviluppatore
   - Vai su **App** → **Aggiorna lista app**

3. **Installa il modulo:**
   - Cerca "AI LiveBot"
   - Clicca **Installa**

4. **Configura provider AI:**
   - Vai su **Impostazioni** → **AI Configuration**
   - Crea nuova configurazione
   - Seleziona provider (**Gemini** o **OpenRouter**)
   - Inserisci API key corrispondente
   - Configura parametri (model_name, temperature, system_prompt)
   - Salva (la configurazione diventerà automaticamente attiva)

---

## ⚙️ Configurazione

### Provider AI

#### Google Gemini
```
Provider: gemini
API Key: YOUR_GEMINI_API_KEY
Model: gemini-2.0-flash-exp (o altro modello)
Temperature: 0.7 (0.0-1.0)
Max Tokens: 1500
```

Ottieni la chiave API: [Google AI Studio](https://aistudio.google.com/app/apikey)

#### OpenRouter
```
Provider: openrouter
API Key: YOUR_OPENROUTER_API_KEY
Model: google/gemini-2.0-flash-exp:free (o altro)
Temperature: 0.7
Max Tokens: 1500
```

Ottieni la chiave API: [OpenRouter](https://openrouter.ai/keys)

### System Prompt

Il system prompt definisce il comportamento dell'AI. Esempio predefinito:

```
Sei un assistente virtuale per un magazzino Odoo. Aiuta gli utenti a:
- Cercare prodotti nel catalogo
- Verificare disponibilità e giacenze
- Creare ordini di vendita
- Validare consegne

Rispondi in italiano, sii conciso e usa emoji per rendere le risposte chiare.
```

### Validazione Automatica

Il sistema valida automaticamente che:
- Per provider **Gemini**: campo `gemini_api_key` sia compilato
- Per provider **OpenRouter**: campo `openrouter_api_key` sia compilato

Errori di validazione mostrano messaggi in italiano:
```
⚠️ Attenzione: per il provider 'gemini' è richiesta la Gemini API Key.
⚠️ Attenzione: per il provider 'openrouter' è richiesta la OpenRouter API Key.
```

### Single-Active Configuration

Il sistema garantisce che **solo una configurazione sia attiva** alla volta:
- Quando crei una nuova config con `active=True`, le altre vengono disattivate
- Quando attivi una config esistente, le altre vengono disattivate automaticamente
- La lista configurazioni mostra tutte (attive e disattivate) senza filtri

---

## 🚀 Utilizzo

### Esempi di Comandi

#### Ricerca Prodotti
```
👤 Cerca prodotti con la parola "cestino"
🤖 Trovati 3 prodotti:
   • Cestino Rosso (ID: 42) - Stock: 15 unità
   • Cestino Blu (ID: 43) - Stock: 8 unità
   • Cestino Verde (ID: 44) - Stock: 0 unità
```

#### Verifica Disponibilità
```
👤 Controlla disponibilità Sedia Ergonomica
🤖 📦 SEDIA ERGONOMICA (ID: 101)
   ✅ Disponibile: 25 unità
   📊 In arrivo: 10 unità
   📊 In uscita: 5 unità
```

#### Creazione Ordine di Vendita
```
👤 Crea ordine vendita per 10 Cestini Rossi per cliente ACME
🤖 📦 RIEPILOGO ORDINE
   Cliente: ACME Corporation
   
   Prodotti richiesti:
   • Cestino Rosso x10 - ✅ Disponibile (stock: 15)
   
   Vuoi confermare la creazione dell'ordine? (rispondi "conferma")
   
👤 conferma
🤖 ✅ Ordine SO042 creato con successo!
```

#### Validazione Consegna
```
👤 Valida consegna WH/OUT/00123
🤖 ✅ Consegna WH/OUT/00123 validata con successo!
   Cliente: ACME Corporation
   Stato: Fatto
```

---

## 🔧 Sviluppo

### Aggiungere Nuove Operazioni

Per estendere le capacità dell'AI, aggiungi metodi in `warehouse_operations.py`:

```python
@api.model
def custom_operation(self, param1, param2):
    """Descrizione operazione"""
    # Logica custom
    return {"status": "success", "data": result}
```

Poi aggiorna il system prompt in `ai_config` per informare l'LLM della nuova funzionalità.

### Modificare Logica Chat

La logica principale è in `ai_chatbot.py`:
- `_call_llm_with_tools()`: Orchestrazione chiamata LLM con tool execution
- `_normalize_product_search_term()`: Normalizzazione termini ricerca
- `format_html_response()`: Formattazione output HTML per chat

### Testing

Testa le operazioni usando la console Python di Odoo:

```python
# Test ricerca prodotti
ops = env['warehouse.operations']
result = ops.search_products(search_term="cestino", limit=10)
print(result)

# Test configurazione AI
config = env['ai.config'].get_active_config()
print(f"Provider attivo: {config.provider}")
```

---

## 🐛 Troubleshooting

### Errore: "Nessuna configurazione AI attiva"
**Causa**: Nessuna configurazione con `active=True`  
**Soluzione**: Vai su **AI Configuration** e attiva una configurazione

### Errore: API Key non valida
**Causa**: Chiave API errata o scaduta  
**Soluzione**: Verifica la chiave API sul sito del provider (Gemini o OpenRouter)

### LLM risponde in inglese invece che italiano
**Causa**: System prompt non specifica lingua italiana  
**Soluzione**: Modifica system prompt aggiungendo: "Rispondi SEMPRE in italiano"

### Ricerca prodotti non trova risultati
**Causa**: Nome prodotto con caratteri speciali o case-sensitive  
**Soluzione**: Il sistema usa ricerca fuzzy, ma verifica che il prodotto esista in Odoo

---

## 📄 Licenza

Questo progetto è rilasciato sotto licenza **LGPL-3**.

---

## 👨‍💻 Autore

**Marco Egidi**  
- GitHub: [@markegidiDev](https://github.com/markegidiDev)
- Repository: [ERP-ChatBot-LLM](https://github.com/markegidiDev/ERP-ChatBot-LLM)

---

## 🤝 Contributi

Contributi, issues e feature requests sono benvenuti!  
Sentiti libero di controllare la [issues page](https://github.com/markegidiDev/ERP-ChatBot-LLM/issues).

---

## ⭐ Supporto

Se questo progetto ti è utile, lascia una stella su GitHub! ⭐
