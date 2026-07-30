DOCUMENTATIE SI PREZENTARE PROIECT REMOTE CONTROL SERVER API

Acest proiect reprezinta un server API complet si un tablou de comanda (Dashboard) dezvoltat pentru gestionarea, monitorizarea si auditarea conexiunilor si dispozitivelor din reteaua RustDesk. Sistemul functioneaza ca un punct central de semnalizare, autentificare si control pentru toti clientii si agentii RustDesk conectati.

Arhitectura backend este construita pe FastAPI si Python, utilizand o baza de date SQLite optimizata pentru stocarea dispozitivelor, utilizatorilor, adresarului si jurnalelor de audit. Serverul include rutine automate de fundal care verifica periodic pulsul (heartbeat) trimis de agenti pentru a determina starea de conectivitate (Online/Offline) si efectueaza verificari active pentru serviciile de retea precum raspunsul la PING si disponibilitatea portului RDP (3389).

Tabloul de comanda (Dashboard) este construit cu o interfata moderna, utilizand CSS Vanilla cu design dark-mode si reactivitate in timp real prin conexiuni WebSocket. Interfata ofera o vizualizare clara a tuturor dispozitivelor inregistrate, starea lor curenta, precum si sesiunile de control de la distanta active in fiecare moment.

Sistemul implementeaza o logica avansata de urmarire a conexiunilor de la dispozitiv la dispozitiv (conceptul de inception). Fiecare sesiune initiata intre doi agenti este inregistrata automat prin apelurile de audit trimise de RustDesk. Interfata afiseaza distinct starea fiecarui endpoint, indicand vizual prin etichete speciale si puncte de stare daca o masina controleaza un alt dispozitiv sau este controlata la randul ei, specificand numele si ID-ul partenerului de sesiune, precum si modul de lucru (Desktop, RDP, Transfer de Fisiere).

Pentru a preveni erorile cauzate de deconectari neasteptate sau intreruperi de retea in care evenimentul de inchidere a conexiunii nu ajunge la API, baza de date filtreaza dinamic sesiunile active. Orice sesiune asociata unui dispozitiv care devine offline sau inactiv este invalidata automat, garantand ca informatiile afisate pe ecran sunt intotdeauna conforme cu realitatea din retea.

Proiectul include de asemenea un jurnal de audit complet si cautare avansata in istoricul de activitate, permitand administratorilor sa inspecteze detaliat fiecare eveniment de conectare, adresele IP sursa si destinatie, timestamp-urile si actiunile efectuate in cadrul retelei.
