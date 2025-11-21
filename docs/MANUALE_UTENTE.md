# 📘 Manuale Utente - AI LiveBot per Odoo

**Versione**: 1.0  
**Data**: Novembre 2025  
**Modulo**: `ai_livebot`

---

## 📋 Indice

1. [Introduzione](#introduzione)
2. [Installazione](#installazione)
3. [Configurazione AI](#configurazione-ai)
4. [Workflow Completo: Gestione Ordini](#workflow-completo-gestione-ordini)
   - [Ricerca Prodotti](#1-ricerca-prodotti)
   - [Creazione Preventivo/Ordine](#2-creazione-preventivo-ordine)
   - [Modifica Ordine (Bozza)](#3-modifica-ordine-bozza)
   - [Conferma Ordine](#4-conferma-ordine)
   - [Annullamento Ordine](#5-annullamento-ordine)
4. [Funzionalità Avanzate](#funzionalità-avanzate)
5. [Esempi Pratici](#esempi-pratici)
6. [Risoluzione Problemi](#risoluzione-problemi)

---

## 🎯 Introduzione

**AI LiveBot** è un assistente intelligente integrato nella chat di Odoo che ti permette di gestire ordini di vendita, preventivi e magazzino usando il linguaggio naturale.

### Cosa puoi fare:
- ✅ Cercare prodotti e servizi nel catalogo
- ✅ Creare preventivi e ordini di vendita con conferma
- ✅ Modificare quantità e prodotti in bozza
- ✅ Confermare ordini (da preventivo a ordine confermato)
- ✅ Annullare ordini in bozza con conferma
- ✅ Controllare disponibilità magazzino
- ✅ Gestire consegne e delivery orders

### Sinonimi supportati:
**"ordine"**, **"preventivo"**, **"quotazione"** e **"offerta"** sono **sinonimi** in Odoo - l'AI li tratta identicamente!

---

## 📦 Installazione

### Requisiti di Sistema

| Requisito | Versione |
|-----------|----------|
| **Odoo** | 18.0 |
| **Python** | 3.10+ |
| **PostgreSQL** | 12+ |

### Dipendenze Python Richieste

Il modulo richiede queste librerie Python:
- `requests` - Per chiamate API HTTP
- `python-dateutil` - Per gestione date avanzata

⚠️ **Importante**: Devi installarle **manualmente** prima di installare il modulo in Odoo!

---

### 📥 Installazione su Windows

#### Passo 1: Installa le Dipendenze Python

**Apri PowerShell** e installa le librerie richieste:

```powershell
# Trova quale Python usa Odoo
where.exe python

# Installa le dipendenze
python -m pip install requests python-dateutil
```

**Se hai problemi**:
```powershell
# Prova con pip direttamente
pip install requests python-dateutil

# Oppure con pip3
pip3 install requests python-dateutil
```

#### Passo 2: Verifica Installazione Dipendenze

```powershell
# Verifica che siano installate
python -c "import requests; import dateutil; print('✅ Dipendenze OK')"
```

Se vedi `✅ Dipendenze OK`, sei pronto! Altrimenti riprova il Passo 1.

#### Passo 3: Copia il Modulo nella Cartella Addons

1. **Scarica o clona** il repository `ai_livebot`
2. **Copia l'intera cartella** `ai_livebot` dentro la cartella addons di Odoo

**Esempio**:
```
C:\odoo_custom\addons\ai_livebot\
    ├── __init__.py
    ├── __manifest__.py
    ├── controllers/
    ├── models/
    ├── views/
    ├── security/
    └── docs/
```

**Percorsi comuni su Windows**:
- Odoo installato con installer: `C:\Program Files\Odoo 18.0\server\addons\`
- Odoo installato manualmente: `C:\odoo\addons\` o `C:\odoo_custom\addons\`

#### Passo 4: Riavvia Odoo

Se Odoo è un **servizio Windows**:
```powershell
# PowerShell come Amministratore
Restart-Service odoo
```

Se Odoo è avviato **manualmente**:
- Ferma il processo (Ctrl+C nella finestra del terminale)
- Riavvia con:
  ```powershell
  python odoo-bin -c odoo.conf
  ```

#### Passo 5: Aggiorna Lista App

1. Apri Odoo nel browser: `http://localhost:8069`
2. Vai su **Impostazioni** (Settings)
3. Attiva **Modalità Sviluppatore**:
   - Scorri in fondo alla pagina → **Attiva la modalità sviluppatore**
4. Vai su **App** nel menu principale
5. Clicca sull'icona **⟳ Aggiorna lista app** (in alto)
6. Nella popup, clicca **Aggiorna**

#### Passo 6: Installa il Modulo

1. Nella schermata **App**, nella barra di ricerca scrivi: `ai_livebot`
2. Dovresti vedere la card del modulo:
   ```
   🤖 AI LiveBot - Warehouse Assistant
   Assistente AI per gestione ordini e magazzino via chat
   Versione 1.0 - Marco Egidi
   ```
3. Clicca su **Installa**
4. Attendi 10-30 secondi mentre Odoo:
   - Crea le tabelle nel database
   - Registra il modulo
   - Carica i file

✅ **Fatto!** Il modulo è installato.

#### Passo 7: Verifica Installazione

Nel menu principale di Odoo dovresti ora vedere:

```
🤖 AI LiveBot
   └── AI Configuration
```

Se non appare:
- Ricarica la pagina (F5)
- Esci e rientra in Odoo
- Controlla che il modulo sia in stato **Installato**

---

### 🔄 Aggiornamento del Modulo

Quando ci sono nuove versioni:

1. **Sostituisci i file** nella cartella `ai_livebot` con la nuova versione
2. **Riavvia Odoo**:
   ```powershell
   Restart-Service odoo
   ```
3. **Aggiorna il modulo**:
   - Vai su **App** → Cerca `ai_livebot`
   - Clicca sul menu **⋮** → **Aggiorna**

---

### 🗑️ Disinstallazione

1. Vai su **App**
2. Cerca `ai_livebot`
3. Clicca sul modulo → **Disinstalla**
4. Conferma l'operazione

⚠️ **Attenzione**: Questo rimuoverà tutti i dati del modulo (configurazioni AI, cronologia chat, ecc.)

Per rimuovere anche i file:
```powershell
Remove-Item -Recurse -Force C:\odoo_custom\addons\ai_livebot
```

---

### 🛠️ Risoluzione Problemi

#### ❌ "Modulo non trovato dopo copia"

**Causa**: La cartella non è nel percorso `addons_path` configurato.

**Soluzione**:
1. Apri il file di configurazione Odoo (es. `odoo.conf`)
2. Cerca la riga `addons_path = ...`
3. Verifica che includa la cartella dove hai copiato `ai_livebot`

**Esempio `odoo.conf`**:
```ini
[options]
addons_path = C:\Program Files\Odoo 18.0\server\addons,C:\odoo_custom\addons
```

#### ❌ "ImportError: No module named 'google.generativeai'"

**Causa**: Le dipendenze Python non sono state installate.

**Soluzione**:
```powershell
# Installa le dipendenze mancanti
python -m pip install requests python-dateutil

# Verifica installazione
python -c "import requests; import dateutil; print('OK')"

# Riavvia Odoo
Restart-Service odoo
```

#### ❌ "Access Denied" durante installazione

**Causa**: L'utente Odoo non ha permessi amministrativi.

**Soluzione**:
- Verifica di essere loggato come **Administrator** in Odoo
- L'utente deve avere il gruppo **Administration / Settings**

#### ❌ Il modulo non appare in "Aggiorna lista app"

**Soluzione**:
1. Verifica che `__manifest__.py` esista nella cartella
2. Controlla i log di Odoo:
   ```powershell
   Get-Content "C:\Program Files\Odoo 18.0\server\odoo.log" -Tail 50
   ```
3. Riavvia Odoo e controlla errori nei log

---

## ⚙️ Configurazione AI

### Prerequisiti
- Modulo `ai_livebot` installato in Odoo 18
- Accesso alla chat interna di Odoo
- Credenziali API per Google Gemini o OpenRouter

### Accesso al Configuratore

1. **Apri il menu**: `AI LiveBot → AI Configuration`
2. **Crea un nuovo profilo** (se non esiste già):
   - Clicca su **"Crea"**
   - Compila i campi richiesti

### Campi del Form di Configurazione

| Campo | Descrizione | Esempio |
|-------|-------------|---------|
| **Nome** | Nome identificativo del profilo | "Produzione 2025" |
| **Attivo** | Abilita/disabilita configurazione | ☑️ (spunta per attivare) |
| **Provider** | Fornitore LLM da usare | Google Gemini / OpenRouter |
| **Model Name** | Nome del modello AI | `gemini-2.5-flash` |
| **Gemini API Key** | Chiave API Google AI Studio | `AIzaSy...` (campo password) |
| **OpenRouter API Key** | Chiave API OpenRouter | `sk-or-v1-...` (campo password) |
| **Temperature** | Creatività dell'AI (0.0-1.0) | `0.7` (default) |
| **System Prompt** | Istruzioni avanzate (opzionale) | *(lascia vuoto)* |

### Come Compilare il Form

#### 1. **Nome Profilo**
Scegli un nome chiaro per identificare il profilo (es. "Vendite Italia", "Test AI").

#### 2. **Attivo**
- ✅ **Spunta**: questo profilo sarà usato dall'AI
- ⚠️ **Nota**: Solo **un profilo può essere attivo alla volta**. Attivandone uno, gli altri vengono disattivati automaticamente.

#### 3. **Provider e Chiavi API**

##### Opzione A: Google Gemini (consigliato)
1. Vai su [Google AI Studio](https://aistudio.google.com/apikey)
2. Crea una **API Key** gratuita
3. Copia la chiave (inizia con `AIzaSy...`)
4. Nel form:
   - **Provider**: seleziona `Google Gemini`
   - **Gemini API Key**: incolla la chiave
   - **Model Name**: scrivi `gemini-2.5-flash` (o `gemini-2.5-pro`)

##### Opzione B: OpenRouter
1. Vai su [OpenRouter](https://openrouter.ai/keys)
2. Crea una **API Key**
3. Copia la chiave (inizia con `sk-or-v1-...`)
4. Nel form:
   - **Provider**: seleziona `OpenRouter`
   - **OpenRouter API Key**: incolla la chiave
   - **Model Name**: scrivi il modello desiderato (es. `google/gemini-2.5-flash`)

#### 4. **Temperature**
- **0.0**: Risposte molto precise e deterministiche
- **0.7**: Bilanciato (default consigliato)
- **1.0**: Più creatività nelle risposte

#### 5. **System Prompt**
⚠️ **NON compilare** questo campo a meno che tu non sappia cosa stai facendo!
Il modulo usa già un prompt ottimizzato interno. Modificarlo può causare malfunzionamenti.

### Validazione della Configurazione

Dopo aver salvato:
- ✅ Se manca la chiave API per il provider scelto, riceverai un **errore di validazione**
- ✅ Il sistema garantisce che ci sia **sempre e solo un profilo attivo**
- ✅ Apri la chat di Odoo e prova: `"Ciao, sei attivo?"`

---

## 🔄 Workflow Completo: Gestione Ordini

### 1. Ricerca Prodotti

L'AI cerca automaticamente i prodotti nel catalogo quando crei un ordine, ma puoi anche cercarli manualmente.

#### Comandi Supportati

| Comando | Cosa fa | Esempio |
|---------|---------|---------|
| **Cerca prodotto specifico** | Trova prodotti per nome | `"cerca sedie"` |
| **Elenca tutti i prodotti** | Mostra tutto il catalogo | `"mostrami tutti i prodotti"` |
| **Cerca solo servizi** | Filtra per tipo servizio | `"elenca i servizi disponibili"` |
| **Cerca solo beni fisici** | Filtra prodotti stoccabili | `"mostrami i beni in magazzino"` |
| **Controlla stock** | Verifica disponibilità | `"quante sedie abbiamo?"` |

#### Esempi Pratici

```
👤 Utente: "cerca tavoli"
🤖 AI: 
✅ Trovati 3 prodotti per "tavoli":
• Tavolo Riunione Grande (ID: 42) - €850,00 - 12 unità
• Tavolo Scrivania (ID: 43) - €320,00 - 45 unità  
• Tavolo Pranzo Esterno (ID: 51) - €480,00 - 8 unità
```

```
👤 Utente: "quanti armadietti abbiamo?"
🤖 AI:
📦 Stock Armadietto (ID: 15):
• Disponibile: 28 unità
• In arrivo: 10 unità
• In uscita: 5 unità
• Totale previsto: 33 unità
```

#### Tipi di Prodotto in Odoo

L'AI distingue automaticamente:
- **Servizi** (`service`): Consegna, Installazione, Manutenzione, ecc.
- **Beni fisici** (`product`): Prodotti stoccabili con quantità in magazzino
- **Prodotti combo** (`combo`): Bundle di prodotti (POS/eCommerce)

---

### 2. Creazione Preventivo / Ordine

#### 🚀 Workflow con Conferma Obbligatoria

L'AI **NON esegue mai direttamente** la creazione di ordini. Segue sempre questo flusso:

1. **Ricerca prodotti** (se necessario)
2. **Mostra riepilogo** con:
   - Cliente
   - Prodotti e quantità
   - Totale stimato
   - Data consegna (se specificata)
3. **Chiede conferma** esplicita
4. **Esegue** solo se confermi con `SÌ` / `CONFERMO` / `OK VAI`

#### Sintassi Comando

```
"crea [ordine/preventivo/quotazione] per [CLIENTE] per [QUANTITÀ PRODOTTO], [QUANTITÀ PRODOTTO], ..."
```

**Parametri opzionali**:
- **Data consegna**: `"...entro il 2025-11-25"` o `"...per domani"`
- **Conferma immediata**: `"...e confermalo"` (salta lo stato bozza)

#### Esempi Passo-Passo

##### Esempio 1: Ordine Semplice

```
👤 Utente: "crea un preventivo per Azure Interior per 5 sedie ufficio e 2 tavoli"

🤖 AI:
✅ Preventivo pronto per conferma:

Cliente: Azure Interior
Prodotti:
• 5x Sedia Ufficio Ergonomica (ID: 38) - €125,00 cad.
• 2x Tavolo Riunione Grande (ID: 42) - €850,00 cad.

Totale stimato: €2.325,00

[PENDING_SO] {"partner_name":"Azure Interior","order_lines":[{"product_id":38,"quantity":5},{"product_id":42,"quantity":2}],"confirm":false}

Confermi? (rispondi SÌ/CONFERMO/OK VAI)
```

```
👤 Utente: "SÌ"

🤖 AI:
✅ Preventivo S00123 creato con successo!
Cliente: Azure Interior
Totale: €2.325,00
Stato: Bozza (Draft)

Puoi modificarlo con: "modifica il preventivo S00123"
Per confermarlo: "conferma l'ordine S00123"
```

##### Esempio 2: Con Data Consegna

```
👤 Utente: "crea ordine per Ready Mat per 10 Assemblaggio mobili e 3 pernottamento in albergo entro il 2025-12-01"

🤖 AI:
✅ Ordine pronto per conferma:

Cliente: Ready Mat
Prodotti:
• 10x Assemblaggio mobili (ID: 38) - €50,00 cad.
• 3x Pernottamento in albergo (ID: 2) - €120,00 cad.

Data consegna: 2025-12-01
Totale stimato: €860,00

[PENDING_SO] {"partner_name":"Ready Mat","order_lines":[{"product_id":38,"quantity":10},{"product_id":2,"quantity":3}],"scheduled_date":"2025-12-01","confirm":false}

Confermi? (rispondi SÌ/CONFERMO/OK VAI)
```

##### Esempio 3: Con Conferma Immediata

```
👤 Utente: "crea ordine per Deco Addict per 3 lampade design e confermalo subito"

🤖 AI:
✅ Ordine pronto per conferma (sarà confermato immediatamente):

Cliente: Deco Addict
Prodotti:
• 3x Lampada Design Moderna (ID: 67) - €180,00 cad.

Totale stimato: €540,00
Stato dopo conferma: Sale Order (genera delivery automatici)

[PENDING_SO] {"partner_name":"Deco Addict","order_lines":[{"product_id":67,"quantity":3}],"confirm":true}

Confermi? (rispondi SÌ/CONFERMO/OK VAI)
```

```
👤 Utente: "CONFERMO"

🤖 AI:
✅ Ordine SO00456 creato E CONFERMATO!
Cliente: Deco Addict
Totale: €540,00
Stato: Sale Order (ordine confermato)
Delivery generati: WH/OUT/00789
```

#### 🛡️ Gestione Prodotti Ambigui

Se il nome prodotto è generico o ci sono più risultati, l'AI mostra le opzioni:

```
👤 Utente: "crea preventivo per Azure Interior per 5 sedie"

🤖 AI:
🔍 Trovati 5 prodotti diversi per "sedie":
• Sedia Ufficio Ergonomica (ID: 38) - €125,00 - 50 unità
• Sedia Riunioni (ID: 39) - €80,00 - 30 unità
• Sedia Bar Alta (ID: 40) - €65,00 - 15 unità
• Sedia Design Plastica (ID: 41) - €45,00 - 100 unità
• Sedia Legno Classica (ID: 42) - €95,00 - 20 unità

Quale vuoi usare? (specifica ID o nome completo)
```

```
👤 Utente: "usa la ID 38"

🤖 AI:
✅ Preventivo pronto per conferma:
Cliente: Azure Interior
Prodotti: 5x Sedia Ufficio Ergonomica (ID: 38) - €125,00 cad.
Totale stimato: €625,00
...
```

#### ⚠️ Annullamento Durante Conferma

```
👤 Utente: "no annulla"

🤖 AI:
❌ Creazione preventivo annullata.
Nessuna modifica effettuata.
```

---

### 3. Modifica Ordine (Bozza)

Puoi modificare ordini **solo se sono in stato Draft (Bozza) o Sent (Inviato)**.

#### Operazioni Supportate

| Operazione | Comando Esempio |
|------------|-----------------|
| **Cambia quantità** | `"modifica l'ordine S00123: cambia sedie a 10"` |
| **Aggiungi prodotto** | `"aggiungi 5 lampade all'ordine S00123"` |
| **Rimuovi prodotto** | `"rimuovi i tavoli dal preventivo S00123"` |
| **Cambia data consegna** | `"sposta la consegna del S00123 al 2025-12-10"` |
| **Modifica multipla** | `"nell'ordine S00123 cambia sedie a 8 e aggiungi 3 armadi"` |

#### Esempi Pratici

##### Esempio 1: Modifica Quantità

```
👤 Utente: "modifica l'ordine S00123: cambia le sedie da 5 a 8"

🤖 AI:
✅ Ordine S00123 aggiornato con successo!

Modifiche effettuate:
• Sedia Ufficio Ergonomica: 5 → 8 unità

Nuovo totale: €2.950,00 (era €2.325,00)
```

##### Esempio 2: Aggiungi Prodotto

```
👤 Utente: "aggiungi 3 lampade design al preventivo S00123"

🤖 AI:
✅ Preventivo S00123 aggiornato!

Nuovi prodotti aggiunti:
• 3x Lampada Design Moderna - €180,00 cad.

Nuovo totale: €3.490,00
```

##### Esempio 3: Modifica Multipla

```
👤 Utente: "nel preventivo S00123 togli i tavoli e aggiungi 2 armadi"

🤖 AI:
✅ Preventivo S00123 aggiornato!

Prodotti rimossi:
• Tavolo Riunione Grande (2 unità)

Prodotti aggiunti:
• 2x Armadio Ufficio - €650,00 cad.

Nuovo totale: €1.925,00
```

##### Esempio 4: Cambia Data Consegna

```
👤 Utente: "sposta la consegna dell'ordine S00123 al 15 dicembre"

🤖 AI:
✅ Data consegna aggiornata!
Ordine: S00123
Nuova data: 2025-12-15
```

#### ⚠️ Limitazioni

**NON puoi modificare ordini confermati** (stato = `sale`):

```
👤 Utente: "modifica l'ordine SO00456: cambia quantità sedie a 10"

🤖 AI:
❌ Impossibile modificare: ordine SO00456 è già confermato (stato: Sale Order)

Soluzioni:
1. Annulla l'ordine e creane uno nuovo
2. Crea un nuovo ordine separato con le modifiche
3. Modifica manualmente il delivery associato (se non ancora evaso)
```

---

### 4. Conferma Ordine

Confermare un ordine significa passarlo da **Bozza (Draft)** a **Ordine di Vendita Confermato (Sale Order)**.

#### Cosa Succede Durante la Conferma

1. ✅ Stato ordine: `draft` → `sale`
2. ✅ **Vengono generati automaticamente i Delivery Orders** (WH/OUT/xxxxx)
3. ✅ Prodotti riservati in magazzino
4. ✅ L'ordine **NON è più modificabile** con `update_sales_order`

#### Sintassi Comando

```
"conferma l'ordine [NOME_ORDINE]"
"conferma il preventivo [NOME_ORDINE]"
```

#### Esempio Passo-Passo

```
👤 Utente: "conferma il preventivo S00123"

🤖 AI:
✅ Ordine S00123 confermato con successo!

Cliente: Azure Interior
Totale: €2.325,00
Stato: Sale Order (confermato)

Delivery generati:
• WH/OUT/00567 - Pronto per evasione
```

#### ⚠️ Casi Particolari

**Ordine già confermato**:
```
👤 Utente: "conferma l'ordine SO00456"

🤖 AI:
❌ Impossibile confermare: ordine già in stato 'Sale Order'
Questo ordine è già confermato o completato.
```

**Ordine non trovato**:
```
👤 Utente: "conferma l'ordine S99999"

🤖 AI:
❌ Ordine 'S99999' non trovato.
Verifica il nome dell'ordine.
```

---

### 5. Annullamento Ordine

#### 🚀 Workflow con Conferma Obbligatoria

L'AI **NON esegue mai direttamente** la cancellazione. Segue sempre questo flusso:

1. **Verifica ordine** (controlla che esista)
2. **Mostra avviso** con:
   - Nome ordine
   - Cliente
   - Totale
   - Messaggio che l'operazione è **irreversibile**
3. **Chiede conferma** esplicita
4. **Esegue cancellazione** solo se confermi con `SÌ` / `CONFERMO`

#### ⚠️ Limitazioni Critiche

**Puoi cancellare SOLO ordini in stato Draft (Bozza)**:
- ✅ `draft` → Cancellazione consentita
- ❌ `sale`, `done`, `cancel` → Cancellazione non consentita

Se l'ordine è confermato, devi annullarlo manualmente da Odoo.

#### Sintassi Comando

```
"annulla l'ordine [NOME_ORDINE]"
"cancella il preventivo [NOME_ORDINE]"
"elimina l'ordine [NOME_ORDINE]"
```

**Nota**: Puoi usare il nome completo (`S00123`) o solo il numero (`76` → cerca `S00076`).

#### Esempi Passo-Passo

##### Esempio 1: Cancellazione con Nome Completo

```
👤 Utente: "cancella il preventivo S00123"

🤖 AI:
⚠️ Attenzione: Stai per cancellare il preventivo S00123
Cliente: Azure Interior
Totale: €2.325,00
Questa operazione è IRREVERSIBILE.

[PENDING_CANCEL] {"order_name":"S00123"}

Sei sicuro? (rispondi SÌ/CONFERMO per procedere)
```

```
👤 Utente: "SÌ"

🤖 AI:
✅ Ordine S00123 cancellato con successo.
```

##### Esempio 2: Cancellazione con Numero

```
👤 Utente: "annulla il preventivo 76"

🤖 AI:
⚠️ Attenzione: Stai per cancellare il preventivo S00076
Cliente: Ready Mat
Totale: €8.000,00
Questa operazione è IRREVERSIBILE.

[PENDING_CANCEL] {"order_name":"S00076"}

Sei sicuro? (rispondi SÌ/CONFERMO per procedere)
```

```
👤 Utente: "CONFERMO"

🤖 AI:
✅ Ordine S00076 cancellato con successo.
```

##### Esempio 3: Annullamento Durante Conferma

```
👤 Utente: "no lascia stare"

🤖 AI:
❌ Cancellazione annullata.
L'ordine S00076 è ancora presente.
```

#### ⚠️ Casi di Errore

**Ordine già confermato**:
```
👤 Utente: "cancella l'ordine SO00456"

🤖 AI:
❌ Cancellazione non consentita: ordine in stato 'sale'
REGOLA ODOO: Solo ordini in bozza (draft) possono essere cancellati via AI.

Soluzione: Annulla manualmente da Odoo → Vendite → Ordini
```

**Ordine già cancellato**:
```
👤 Utente: "annulla l'ordine S00100"

🤖 AI:
❌ Ordine S00100 è già cancellato.
```

**Ordine non trovato**:
```
👤 Utente: "cancella il preventivo S99999"

🤖 AI:
❌ Ordine 'S99999' non trovato.
Verifica il nome dell'ordine.
```

---

## 🚀 Funzionalità Avanzate

### Gestione Multi-Prodotto (Batch Operations)

L'AI supporta richieste con **multipli prodotti** in un solo comando.

#### Esempio: Creazione Ordine con 3 Prodotti

```
👤 Utente: "crea preventivo per Ready Mat per 3 sedie ufficio, 5 tavoli pranzo e 2 armadi"

🤖 AI:
[Esegue automaticamente 3 ricerche in parallelo]
[FUNCTION:search_products|search_term:sedia ufficio|limit:5]
[FUNCTION:search_products|search_term:tavolo pranzo|limit:5]
[FUNCTION:search_products|search_term:armadio|limit:5]

✅ Preventivo pronto per conferma:
Cliente: Ready Mat
Prodotti:
• 3x Sedia Ufficio Ergonomica (ID: 38) - €125,00 cad.
• 5x Tavolo Pranzo Esterno (ID: 51) - €480,00 cad.
• 2x Armadio Ufficio (ID: 15) - €650,00 cad.

Totale stimato: €4.075,00
...
```

### Gestione Stock e Disponibilità

#### Verifica Stock Prodotto

```
👤 Utente: "quanti armadietti abbiamo?"

🤖 AI:
📦 Stock Armadietto (ID: 15):
• Disponibile ora: 28 unità
• In arrivo: 10 unità
• Prenotati: 5 unità
• Disponibilità futura: 33 unità
```

### Gestione Delivery Orders

**Nota**: I delivery sono generati automaticamente quando confermi un ordine.

#### Visualizza Consegne Pendenti

```
👤 Utente: "mostra le consegne in uscita"

🤖 AI:
📦 Consegne in uscita (10 totali):

WH/OUT/00567 - Azure Interior - €2.325,00
• Stato: Pronto
• Prodotti: 8x Sedia Ufficio, 2x Tavolo Riunione

WH/OUT/00568 - Ready Mat - €8.000,00
• Stato: In attesa
• Prodotti: 10x Assemblaggio mobili, 3x Pernottamento
...
```

#### Valida Consegna (Evadi)

```
👤 Utente: "valida la consegna WH/OUT/00567"

🤖 AI:
✅ Delivery WH/OUT/00567 validato con successo!
Tutti i prodotti sono stati evasi.
```

---

## 📚 Esempi Pratici Completi

### Scenario 1: Nuovo Preventivo da Zero

```
# Step 1: Cerca prodotti
👤 "cerca lampade"
🤖 [Lista lampade con prezzi e stock]

# Step 2: Crea preventivo
👤 "crea preventivo per Deco Addict per 10 Lampada Design Moderna"
🤖 [Riepilogo + richiesta conferma]

# Step 3: Conferma creazione
👤 "SÌ"
🤖 ✅ Preventivo S00200 creato!

# Step 4: Modifica quantità
👤 "cambia le lampade a 12 nel preventivo S00200"
🤖 ✅ Preventivo aggiornato! 10 → 12 unità

# Step 5: Aggiungi prodotto
👤 "aggiungi 5 sedie design al preventivo S00200"
🤖 ✅ 5x Sedia Design Plastica aggiunte!

# Step 6: Conferma ordine
👤 "conferma l'ordine S00200"
🤖 ✅ Ordine confermato! Delivery WH/OUT/00789 generato
```

### Scenario 2: Annullamento Preventivo

```
# Step 1: Visualizza ordine
👤 "mostra i dettagli del preventivo S00200"
🤖 [Riepilogo completo ordine]

# Step 2: Richiesta cancellazione
👤 "annulla il preventivo 200"
🤖 ⚠️ Stai per cancellare S00200 (Deco Addict - €2.385,00)
   Questa operazione è IRREVERSIBILE.
   Sei sicuro? (SÌ/CONFERMO)

# Step 3: Conferma cancellazione
👤 "CONFERMO"
🤖 ✅ Ordine S00200 cancellato con successo
```

### Scenario 3: Ordine con Conferma Immediata

```
👤 "crea ordine per Azure Interior per 20 sedie ufficio e 10 tavoli riunione, consegna per il 2025-12-20, e confermalo subito"

🤖 [Ricerca prodotti automatica]
✅ Ordine pronto per conferma (sarà confermato immediatamente):
Cliente: Azure Interior
Prodotti:
• 20x Sedia Ufficio Ergonomica - €125,00 cad.
• 10x Tavolo Riunione Grande - €850,00 cad.
Data consegna: 2025-12-20
Totale stimato: €11.000,00
Confermi? (SÌ/CONFERMO/OK VAI)

👤 "SÌ"

🤖 ✅ Ordine SO00789 creato E CONFERMATO!
Delivery generati: WH/OUT/01234
Stato: Sale Order (confermato)
```

---

## 🛠️ Risoluzione Problemi

### L'AI non risponde

**Cause possibili**:
1. ❌ Nessun profilo configurato attivo
2. ❌ Chiave API non valida o scaduta
3. ❌ Provider LLM non raggiungibile

**Soluzione**:
- Controlla `AI LiveBot → AI Configuration`
- Verifica che ci sia **una configurazione attiva** (spunta ✅)
- Testa la chiave API sul sito del provider

### "Errore: Ordine non modificabile"

**Causa**: Stai cercando di modificare un ordine **già confermato**.

**Soluzione**:
- Modifica ordini SOLO in stato `draft` o `sent`
- Per ordini confermati: annulla manualmente e crea nuovo ordine

### "Prodotto non trovato"

**Causa**: Nome prodotto non esiste nel catalogo.

**Soluzione**:
```
👤 "mostrami tutti i prodotti"
🤖 [Lista completa catalogo]

# Usa ID esatto o nome completo
👤 "crea ordine per Azure Interior per 5 prodotti ID 38"
```

### L'AI mostra troppe opzioni

**Causa**: Nome prodotto troppo generico (es. "sedia").

**Soluzione**:
- Sii più specifico: `"sedia ufficio ergonomica"` invece di `"sedia"`
- Oppure scegli dalla lista mostrata dall'AI specificando l'ID

### Cancellazione non funziona

**Verifica**:
1. Ordine in stato `draft`? → ✅ Cancellazione OK
2. Ordine già confermato (`sale`)? → ❌ Annulla manualmente da Odoo

### Conferma non genera delivery

**Causa**: Prodotti senza tipo `product` (es. solo servizi).

**Nota**: I delivery vengono generati automaticamente SOLO per prodotti stoccabili (`product`).
I servizi (`service`) non generano delivery.

---

## 📞 Supporto

Per ulteriori informazioni o problemi:
- 📧 Email: [supporto]
- 📖 Documentazione Odoo: [docs.odoo.com](https://docs.odoo.com)
- 🐛 Bug report: [repository GitHub]

---

**© 2025 Marco Egidi - AI LiveBot v1.0**
