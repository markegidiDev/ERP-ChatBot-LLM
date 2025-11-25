/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { Composer } from "@mail/core/common/composer";
import { useState } from "@odoo/owl";

patch(Composer.prototype, {
    setup() {
        super.setup(...arguments);

        console.log("Composer dettatura: setup", this);

        this.dictationState = useState({
            isListening: false,
            error: null,
        });

        // Inizializza Web Speech API (usiamo DI NUOVO webkitSpeechRecognition come avevi tu)
        if ("webkitSpeechRecognition" in window) {
            this.recognition = new webkitSpeechRecognition();
            this.recognition.continuous = true; // Continua a registrare anche se fai pause
            this.recognition.interimResults = true; // Scrive mentre parli
            this.recognition.lang = "it-IT"; // Italiano

            // Arrow function: `this` rimane il Composer
            this.recognition.onresult = (event) => {
                let finalTranscript = "";
                let interimTranscript = "";

                for (let i = event.resultIndex; i < event.results.length; ++i) {
                    if (event.results[i].isFinal) {
                        finalTranscript += event.results[i][0].transcript;
                    } else {
                        interimTranscript += event.results[i][0].transcript;
                    }
                }

                if (!finalTranscript) {
                    return;
                }

                console.log("Trascrizione finale:", finalTranscript);


                // Cerchiamo textarea del composer
                const textarea =
                    document.querySelector("textarea.o-mail-Composer-input") ||
                    document.querySelector("#userInputText"); // fallback per moduli custom

                if (!textarea) {
                    console.warn("Textarea globale del composer non trovato");
                    return;
                }

                const currentText = textarea.value || "";
                const separator =
                    currentText.length > 0 && !currentText.endsWith(" ") ? " " : "";
                const newText = currentText + separator + finalTranscript;

                console.log("Valore prima:", textarea.value);
                console.log("Valore dopo:", newText);

                // 1) scriviamo nel DOM
                textarea.value = newText;

                // 2) notifichiamo Odoo (come se fosse input da tastiera)
                const inputEvent = new Event("input", {
                    bubbles: true,
                    cancelable: true,
                });
                textarea.dispatchEvent(inputEvent);
            };


            this.recognition.onerror = (event) => {
                console.error("Errore dettatura:", event.error);
                this.dictationState.isListening = false;
                this.dictationState.error = "Errore microfono";
            };

            this.recognition.onend = () => {
                if (this.dictationState.isListening) {
                    this.dictationState.isListening = false;
                    // se vuoi "sempre acceso", potresti richiamare start qui
                    // this.recognition.start();
                }
            };
        } else {
            console.warn("webkitSpeechRecognition non disponibile nel browser");
            this.recognition = null;
        }
    },

    toggleDictation() {
        console.log(
            "toggleDictation chiamato, isListening=",
            this.dictationState.isListening,
            " recognition=",
            this.recognition
        );

        if (!this.recognition) {
            alert(
                "Il tuo browser non supporta la dettatura vocale (usa Chrome/Edge)."
            );
            return;
        }

        if (this.dictationState.isListening) {
            this.recognition.stop();
            this.dictationState.isListening = false;
        } else {
            this.dictationState.error = null;
            this.recognition.start();
            this.dictationState.isListening = true;
        }
    },
});
