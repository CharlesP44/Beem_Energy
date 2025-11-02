# <img src="https://beem.energy/splash/img/dark-1x.png" alt="Beem Energy" width="25" height="auto"/> Beem Energy - Intégration Home Assistant
 
Intégration non officielle permettant de connecter l'ensemble de vos équipements Beem Energy à Home Assistant. 

Suivez votre production solaire, l'état de votre batterie et votre consommation en temps réel.

[![Buy Me a Coffee](https://img.shields.io/badge/buymeacoffee-donate-yellow.svg?logo=buymeacoffee)](https://www.buymeacoffee.com/CharlesP44) [![HACS Validation](https://github.com/CharlesP44/Beem_Energy/actions/workflows/hacs.yml/badge.svg)](https://github.com/CharlesP44/Beem_Energy/actions/workflows/hacs.yml) [![HassFest Validation](https://github.com/CharlesP44/Beem_Energy/actions/workflows/hassfest.yml/badge.svg)](https://github.com/CharlesP44/Beem_Energy/actions/workflows/hassfest.yml)


## ✨ Fonctionnalités Principales

-   **Suivi en Temps Réel** : Données de puissance (W) pour la production solaire, la batterie, et le réseau, mises à jour via MQTT.
-   **Tableau de Bord Énergie** : Toutes les entités d'énergie (kWh) nécessaires pour une intégration avec le tableau de bord Énergie de Home Assistant.
-   **Services d'Historique** : Exportez vos données historiques depuis l'API Beem et importez-les pour remplir les statistiques de Home Assistant.

### Compatibilité des Appareils

| Appareil | Statut |
| :--- | :--- |
| ✅ **Beem Battery** | Entièrement supportée. |
| ✅ **BeemBox / BeemOn** | Entièrement supportée. |
| 🛠️ **Beem EnergySwitch** | Partiellement supporté. |

---

## 🛠️ Installation
L'installation via HACS (Home Assistant Community Store) est la méthode recommandée, car elle gère les mises à jour pour vous.

1.  Ouvrez HACS dans Home Assistant.
2.  Recherchez `Beem Energy` et cliquez sur `Installer`.
3.  **Redémarrez Home Assistant**. C'est une étape obligatoire.
4.  **Ajoutez l'intégration** via `Paramètres > Appareils et services > + AJOUTER UNE INTÉGRATION` et recherchez `Beem Energy`.
5.  Suivez les instructions pour entrer vos identifiants Beem.

➡️ Pour des instructions plus détaillées, consultez la page d'installation du Wiki :  
**[📖 1. Guide d'Installation et Configuration](https://github.com/CharlesP44/Beem_Energy/wiki/1.-Installation-et-Configuration.md)**


## 📚 Documentation Complète (Wiki)

Toute la documentation détaillée de l'intégration se trouve sur le **[Wiki du projet](https://github.com/CharlesP44/Beem_Energy/wiki)**. Vous y trouverez des guides pas à pas pour :

-   **[Configurer le Tableau de Bord Énergie](https://github.com/CharlesP44/Beem_Energy/wiki/2.-Intégration-au-Tableau-de-Bord-Énergie.md)**
-   **[Utiliser la carte Power Flow Card Plus](https://github.com/CharlesP44/Beem_Energy/wiki/3.-Utilisation-avec-Power-Flow-Card-Plus.md)**
-   **[Comprendre toutes les entités fournies](https://github.com/CharlesP44/Beem_Energy/wiki/4.-Entités-Fournies-par-l'Intégration.md)**
-   **[Exporter et Importer vos données historiques](https://github.com/CharlesP44/Beem_Energy/wiki/5.-Services-:-Export-et-Import-de-Données.md)**
-   **[Résoudre les problèmes courants (FAQ)](https://github.com/CharlesP44/Beem_Energy/wiki/6.-Dépannage-et-FAQ.md)**

---

### 👨‍💻 Contribution et Support

🧑‍💻 Auteur : @CharlesP44

Cette intégration est un projet personnel maintenu sur mon temps libre. Si vous rencontrez un bug ou avez une suggestion d'amélioration, n'hésitez pas à **[ouvrir une Issue sur GitHub](https://github.com/CharlesP44/Beem_Energy/issues/new/choose)**.

---

## 🙏 Remerciements

Un grand merci à la communauté **HACF** (Home Assistant Communauté Francophone) pour les échanges fructueux et en particulier à **@jrvrcd** pour son aide précieuse sur la phase d'authentification.

---

## ☕ Soutien

Si vous appréciez cette intégration et souhaitez soutenir son développement, vous pouvez m'offrir un café ! Votre soutien est grandement apprécié.

[![Buy Me a Coffee](https://img.shields.io/badge/buymeacoffee-donate-yellow.svg?logo=buymeacoffee)](https://www.buymeacoffee.com/CharlesP44)

Merci ! 🙏

---

## 📄 Licence

Ce projet est distribué sous la licence MIT. Voir le fichier [LICENSE](LICENSE) pour plus d’informations.

**Avertissement :** Cette intégration n'est pas officiellement affiliée, maintenue ou sponsorisée par Beem Energy.
