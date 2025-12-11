#!/bin/bash

# ============================================================
# Advanced Git Helper Script - v2.0
# Komplette Branch-Management, Merge, Commit & Release-Lösung
# Optimiert für Single-Developer Home Lab
# ============================================================

# Weniger Dekor, klarer Output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Pager unterdrücken, damit kein „q“ nötig ist
export GIT_PAGER=cat
git_cmd() {
    git --no-pager "$@"
}

# ============================================================
# FUNKTIONEN
# ============================================================

# Repository-Check
check_git_repo() {
    if ! git rev-parse --git-dir > /dev/null 2>&1; then
        echo -e "${RED}❌ Fehler: Nicht in einem Git-Repository!${NC}"
        exit 1
    fi
}

# Hauptmenü
show_main_menu() {
    clear
    echo "========================================"
    echo "         Git Helper - kompakt"
    echo "========================================"
    echo ""
    echo "Hauptmenü:"
    echo "1) Workflow (Add/Commit/Tag/Push)"
    echo "2) Branches"
    echo "3) Merge"
    echo "4) Tools"
    echo "5) Status & Info"
    echo "6) Beenden"
    echo ""
    read -n 1 -p "Wähle eine Option [1-6]: " main_option
    echo
}

# ============================================================
# 1) GIT WORKFLOW - Add, Commit, Tag, Push
# ============================================================

git_workflow() {
    echo ""
    echo -e "${YELLOW}📝 === GIT WORKFLOW ===${NC}"
    echo ""
    echo -e "${YELLOW}Aktueller Git-Status:${NC}"
    git_cmd status --short
    echo ""

    # Git add
    read -n 1 -p "Alle Änderungen hinzufügen? [j/N]: " -r
    echo
    if [[ $REPLY =~ ^[Jj]$ ]]; then
        if [ -f .gitignore ]; then
            git_cmd add -u
            echo -e "${GREEN}✓ Geänderte/verfolgte Dateien hinzugefügt${NC}"
            read -n 1 -p "Auch neue (nicht ignorierte) Dateien hinzufügen? [j/N]: " -r
            echo
            if [[ $REPLY =~ ^[Jj]$ ]]; then
                git_cmd add .
                echo -e "${GREEN}✓ Neue Dateien hinzugefügt (Git respektiert .gitignore)${NC}"
            fi
        else
            git_cmd add .
            echo -e "${GREEN}✓ Alle Dateien hinzugefügt${NC}"
        fi
    else
        echo -e "${YELLOW}→ Übersprungen${NC}"
        return
    fi

    # Commit-Nachricht
    echo ""
    read -p "Commit-Nachricht eingeben: " commit_msg
    if [ -z "$commit_msg" ]; then
        echo -e "${RED}❌ Fehler: Commit-Nachricht erforderlich!${NC}"
        return
    fi

    git commit -m "$commit_msg"
    echo -e "${GREEN}✓ Commit erstellt${NC}"

    # Version Tag
    echo ""
    echo -e "${YELLOW}Verfügbare Tags:${NC}"
    if git_cmd tag -l > /dev/null 2>&1 && [ $(git_cmd tag -l | wc -l) -gt 0 ]; then
        git_cmd tag -l | sort -V | tail -5
        LAST_TAG=$(git_cmd tag -l | sort -V | tail -1)
        echo -e "${BLUE}Letzter Tag: $LAST_TAG${NC}"
    else
        echo "Noch keine Tags vorhanden"
        LAST_TAG="0.0.0"
    fi

    # Versionsnummer automatisch erhöhen
    IFS='.' read -r -a version_parts <<< "${LAST_TAG#v}"
    MAJOR=${version_parts[0]:-0}
    MINOR=${version_parts[1]:-0}
    PATCH=${version_parts[2]:-0}
    NEXT_PATCH=$((PATCH + 1))
    SUGGESTED_VERSION="${MAJOR}.${MINOR}.${NEXT_PATCH}"

    echo ""
    read -p "Version taggen? [j/N]: " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Jj]$ ]]; then
        read -p "Version [${SUGGESTED_VERSION}]: " version_input
        VERSION=${version_input:-$SUGGESTED_VERSION}

        if ! [[ $VERSION =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
            echo -e "${RED}❌ Ungültig! Format: X.Y.Z${NC}"
            return
        fi

        git_cmd tag -a "v$VERSION" -m "Release $VERSION"
        echo -e "${GREEN}✓ Tag v$VERSION erstellt${NC}"
    fi

    # Push
    echo ""
    echo -e "${YELLOW}Verfügbare Remote-Branches:${NC}"
    git_cmd branch -r | grep -v HEAD
    echo ""
    read -p "Zum Remote pushen? [j/N]: " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Jj]$ ]]; then
        CURRENT_BRANCH=$(git_cmd rev-parse --abbrev-ref HEAD)
        git_cmd push origin $CURRENT_BRANCH
        if [ -n "$VERSION" ]; then
            git_cmd push origin "v$VERSION"
            echo -e "${GREEN}✓ Tag v$VERSION gepusht${NC}"
        fi
        echo -e "${GREEN}✓ Commits gepusht${NC}"
    fi

    echo ""
    read -p "Drücke Enter zum Fortfahren..."
}

# ============================================================
# 2) BRANCH MANAGEMENT
# ============================================================

branch_management() {
    while true; do
        clear
    echo -e "BRANCH MANAGEMENT"
    echo ""
    echo -e "${YELLOW}Aktuelle Branches:${NC}"
    git_cmd branch -v
        echo ""
        echo "1) 🆕 Neuen Branch erstellen"
        echo "2) 🔄 Zu anderem Branch wechseln"
        echo "3) 🗑️  Branch löschen"
        echo "4) 📋 Branch-Info anzeigen"
        echo "5) 🔙 Zurück zum Hauptmenü"
        echo ""
    read -n 1 -p "Wähle Option [1-5]: " branch_option
    echo

        case $branch_option in
            1) create_branch ;;
            2) switch_branch ;;
            3) delete_branch ;;
            4) show_branch_info ;;
            5) break ;;
            *) echo -e "${RED}Ungültig!${NC}" ;;
        esac
    done
}

create_branch() {
    echo ""
    echo -e "${YELLOW}🆕 Neuen Branch erstellen${NC}"
    echo ""
    echo "Empfohlene Namen: feature, gui, backend, bugfix, docs"
    echo "Beispiel: 'gui' → Branch heißt dann 'gui'"
    echo ""
    read -p "Branch-Name eingeben: " branch_name

    if [ -z "$branch_name" ]; then
        echo -e "${RED}❌ Branch-Name erforderlich!${NC}"
        return
    fi

    # Branch Namen prüfen
    if git rev-parse --verify "$branch_name" > /dev/null 2>&1; then
        echo -e "${RED}❌ Branch '$branch_name' existiert bereits!${NC}"
        return
    fi

    git_cmd branch "$branch_name"
    echo -e "${GREEN}✓ Branch '$branch_name' erstellt${NC}"
    echo ""
    read -p "Zu diesem Branch wechseln? [j/N]: " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Jj]$ ]]; then
        git_cmd checkout "$branch_name"
        echo -e "${GREEN}✓ Zu '$branch_name' gewechselt${NC}"
    fi
    echo ""
    read -p "Drücke Enter zum Fortfahren..."
}

switch_branch() {
    echo ""
    echo -e "${YELLOW}🔄 Zu anderem Branch wechseln${NC}"
    echo ""

    # Prüfe ob es uncommitted changes gibt
    if ! git_cmd diff-index --quiet HEAD --; then
        echo -e "${RED}⚠️  Warnung: Es gibt uncommitted changes!${NC}"
        echo "Diese könnten verloren gehen. Commit oder stash erst."
        echo ""
        read -p "Trotzdem wechseln? [j/N]: " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Jj]$ ]]; then
            return
        fi
    fi

    echo -e "${YELLOW}Verfügbare Branches:${NC}"
    git_cmd branch -v | nl
    echo ""
    read -p "Wähle Branch-Nummer: " branch_num

    # Array der Branches erstellen
    mapfile -t branches < <(git_cmd branch | sed 's/*.*$//' | sed 's/^[[:space:]]*//') 

    if ! [[ $branch_num =~ ^[0-9]+$ ]] || [ $branch_num -lt 1 ] || [ $branch_num -gt ${#branches[@]} ]; then
        echo -e "${RED}❌ Ungültige Nummer!${NC}"
        return
    fi

    target_branch=${branches[$((branch_num - 1))]%% *}
    git_cmd checkout "$target_branch"
    echo -e "${GREEN}✓ Zu '$target_branch' gewechselt${NC}"
    echo ""
    read -p "Drücke Enter zum Fortfahren..."
}

delete_branch() {
    echo ""
    echo -e "${YELLOW}🗑️  Branch löschen${NC}"
    echo ""
    echo -e "${RED}⚠️  WARNUNG: Dies kann nicht rückgängig gemacht werden!${NC}"
    echo ""
    echo -e "${YELLOW}Verfügbare Branches (außer current):${NC}"
    git_cmd branch -v | grep -v "^\*" | nl
    echo ""
    read -p "Wähle zu löschenden Branch: " branch_num

    mapfile -t branches < <(git_cmd branch | grep -v "^\*" | sed 's/^[[:space:]]*//') 

    if ! [[ $branch_num =~ ^[0-9]+$ ]] || [ $branch_num -lt 1 ] || [ $branch_num -gt ${#branches[@]} ]; then
        echo -e "${RED}❌ Ungültig!${NC}"
        return
    fi

    delete_target=${branches[$((branch_num - 1))]%% *}

    echo ""
    echo -e "${YELLOW}Branch zum Löschen: $delete_target${NC}"
    read -p "Bestätigen? [j/N]: " -n 1 -r
    echo

    if [[ ! $REPLY =~ ^[Jj]$ ]]; then
        echo -e "${YELLOW}→ Abgebrochen${NC}"
        return
    fi

    git_cmd branch -d "$delete_target" 2>/dev/null
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ Branch '$delete_target' gelöscht${NC}"
    else
        echo -e "${YELLOW}→ Branch hat ungemergte Commits. Force-Delete? [j/N]: ${NC}" -n 1 -r
        read
        if [[ $REPLY =~ ^[Jj]$ ]]; then
            git_cmd branch -D "$delete_target"
            echo -e "${GREEN}✓ Branch force-gelöscht${NC}"
        fi
    fi
    echo ""
    read -p "Drücke Enter zum Fortfahren..."
}

show_branch_info() {
    echo ""
    echo -e "${YELLOW}📋 Branch-Information${NC}"
    echo ""
    CURRENT=$(git_cmd rev-parse --abbrev-ref HEAD)
    echo -e "${CYAN}Aktueller Branch: ${GREEN}$CURRENT${NC}"
    echo ""
    echo -e "${YELLOW}Branch-Liste mit letztem Commit:${NC}"
    git_cmd branch -v
    echo ""
    echo -e "${YELLOW}Commits im aktuellen Branch:${NC}"
    git_cmd log --oneline -5
    echo ""
    read -p "Drücke Enter zum Fortfahren..."
}

# ============================================================
# 3) BRANCH MERGING
# ============================================================

branch_merging() {
    echo ""
    echo -e "${YELLOW}🔗 === BRANCH MERGING ===${NC}"
    echo ""
    echo -e "${CYAN}Aktueller Branch:${NC}"
    CURRENT_BRANCH=$(git_cmd rev-parse --abbrev-ref HEAD)
    echo "$CURRENT_BRANCH"
    echo ""

    # Zeige Branches an
    echo -e "${YELLOW}Alle Branches:${NC}"
    git_cmd branch -v | nl
    echo ""

    read -p "Wähle Source-Branch zum Mergen (Nummer): " source_num

    mapfile -t branches < <(git_cmd branch | sed 's/^[[:space:]]*//;s/\*//')

    if ! [[ $source_num =~ ^[0-9]+$ ]] || [ $source_num -lt 1 ] || [ $source_num -gt ${#branches[@]} ]; then
        echo -e "${RED}❌ Ungültig!${NC}"
        return
    fi

    SOURCE_BRANCH=${branches[$((source_num - 1))]%% *}

    if [ "$SOURCE_BRANCH" = "$CURRENT_BRANCH" ]; then
        echo -e "${RED}❌ Kann Branch nicht in sich selbst mergen!${NC}"
        return
    fi

    echo ""
    echo -e "${MAGENTA}Merge-Plan:${NC}"
    echo "Source: $SOURCE_BRANCH"
    echo "Ziel: $CURRENT_BRANCH"
    echo ""
    echo -e "${YELLOW}Commits im Source-Branch:${NC}"
    git_cmd log --oneline $CURRENT_BRANCH..$SOURCE_BRANCH
    echo ""

    read -p "Merge durchführen? [j/N]: " -n 1 -r
    echo

    if [[ ! $REPLY =~ ^[Jj]$ ]]; then
        echo -e "${YELLOW}→ Merge abgebrochen${NC}"
        return
    fi

    # Merge durchführen
    git_cmd merge "$SOURCE_BRANCH"

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ Merge erfolgreich!${NC}"
        echo ""
        read -p "Nach erfolgreichem Merge Branch löschen? [j/N]: " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Jj]$ ]]; then
            git_cmd branch -d "$SOURCE_BRANCH"
            echo -e "${GREEN}✓ Branch '$SOURCE_BRANCH' gelöscht${NC}"
        fi
    else
        echo -e "${RED}❌ Merge hat Konflikte!${NC}"
        echo -e "${YELLOW}Betroffene Dateien:${NC}"
        git_cmd status
        echo ""
        echo -e "${YELLOW}Konflikte manuell in Editor beheben oder verwenden:${NC}"
        echo "  git merge --abort  (Merge abbrechen)"
        echo "  git merge --continue (nach Konflikt-Fix)"
    fi

    echo ""
    read -p "Drücke Enter zum Fortfahren..."
}

# ============================================================
# 4) DATEI & REPOSITORY TOOLS
# ============================================================

tools_menu() {
    while true; do
        clear
        echo -e "TOOLS"
        echo "1) Datei wiederherstellen"
        echo "2) Repository zurücksetzen"
        echo "3) Stash anzeigen & verwalten"
        echo "4) Hard Reset & Pull von origin (alles verwerfen)"
        echo "5) Cleanup (gelöschte Remote-Branches entfernen)"
        echo "6) Zurück zum Hauptmenü"
        echo ""
        read -n 1 -p "Wähle Option [1-6]: " tools_option
        echo

        case $tools_option in
            1) restore_file ;;
            2) reset_repository ;;
            3) manage_stash ;;
            4) hard_reset_and_pull ;;
            5) cleanup_branches ;;
            6) break ;;
            *) echo -e "${RED}Ungültig!${NC}" ;;
        esac
    done
}

restore_file() {
    echo ""
    echo -e "${YELLOW}💾 Datei wiederherstellen${NC}"
    echo ""
    echo -e "${CYAN}Methoden:${NC}"
    echo "1) Aus letztem Commit (uncommitted changes verwerfen)"
    echo "2) Aus spezifischem Commit"
    echo "3) Zurück"
    echo ""
    read -p "Wähle Methode [1-3]: " method

    case $method in
        1)
            echo ""
            echo -e "${YELLOW}Geänderte Dateien:${NC}"
            mapfile -t modified < <(git_cmd status --short | awk '{print $2}')
            if [ ${#modified[@]} -eq 0 ]; then
                echo -e "${RED}Keine geänderten Dateien${NC}"
                return
            fi
            for i in "${!modified[@]}"; do
                echo "$((i+1))) ${modified[$i]}"
            done
            echo ""
            read -p "Wähle Datei: " file_idx
            if [[ $file_idx =~ ^[0-9]+$ ]] && [ $file_idx -ge 1 ] && [ $file_idx -le ${#modified[@]} ]; then
                file_path=${modified[$((file_idx-1))]}
            git_cmd checkout -- "$file_path"
                echo -e "${GREEN}✓ '$file_path' wiederhergestellt${NC}"
            fi
            ;;
        2)
            echo ""
            echo -e "${YELLOW}Letzte 10 Commits:${NC}"
            git_cmd log --oneline -10
            echo ""
            read -p "Commit-Hash eingeben: " commit_hash
            if [ -z "$commit_hash" ]; then
                return
            fi
            echo ""
            mapfile -t commit_files < <(git_cmd diff-tree --no-commit-id --name-only -r "$commit_hash")
            if [ ${#commit_files[@]} -eq 0 ]; then
                echo -e "${RED}Keine Dateien in diesem Commit${NC}"
                return
            fi
            for i in "${!commit_files[@]}"; do
                echo "$((i+1))) ${commit_files[$i]}"
            done
            echo ""
            read -p "Wähle Datei: " file_idx
            if [[ $file_idx =~ ^[0-9]+$ ]] && [ $file_idx -ge 1 ] && [ $file_idx -le ${#commit_files[@]} ]; then
                file_path=${commit_files[$((file_idx-1))]}
                git_cmd checkout "$commit_hash" -- "$file_path"
                echo -e "${GREEN}✓ '$file_path' wiederhergestellt${NC}"
            fi
            ;;
    esac

    echo ""
    read -p "Drücke Enter zum Fortfahren..."
}

reset_repository() {
    echo ""
    echo -e "${RED}🔙 Repository zurücksetzen${NC}"
    echo -e "${RED}⚠️  WARNUNG: Dies löscht lokale Änderungen!${NC}"
    echo ""
    echo "1) Zu letztem Commit (working directory löschen)"
    echo "2) Einen Commit zurück (letzter Commit löschen)"
    echo "3) Auf bestimmten Commit zurück (Hash auswählen)"
    echo "4) Abbrechen"
    echo ""
    read -n 1 -p "Option [1-4]: " reset_opt
    echo

    case $reset_opt in
        1)
            read -p "Wirklich alle lokalen Änderungen löschen? [j/N]: " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Jj]$ ]]; then
                git_cmd reset --hard HEAD
                git_cmd clean -fd
                echo -e "${GREEN}✓ Repository zurückgesetzt${NC}"
            fi
            ;;
        2)
            read -p "Wirklich letzten Commit löschen? [j/N]: " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Jj]$ ]]; then
                git_cmd reset --hard HEAD~1
                echo -e "${GREEN}✓ Letzter Commit gelöscht${NC}"
            fi
            ;;
        3)
            echo ""
            echo "Letzte Commits:"
            git_cmd log --oneline -15
            echo ""
            read -p "Commit-Hash oder Kurz-Hash: " commit_hash
            if [ -z "$commit_hash" ]; then
                echo -e "${YELLOW}→ Abgebrochen${NC}"
                return
            fi
            echo -n "Hard reset auf $commit_hash ausführen? [j/N]: "
            read -n 1 -r confirm
            echo
            if [[ $confirm =~ ^[Jj]$ ]]; then
                git_cmd reset --hard "$commit_hash"
                git_cmd clean -fd
                echo -e "${GREEN}✓ Reset auf $commit_hash durchgeführt${NC}"
            else
                echo -e "${YELLOW}→ Abgebrochen${NC}"
            fi
            ;;
    esac

    echo ""
    read -p "Drücke Enter zum Fortfahren..."
}

hard_reset_and_pull() {
    echo ""
    echo -e "${RED}⚠️  Hard Reset & Pull${NC}"
    echo "Verwirft ALLE lokalen Änderungen/Commits und setzt Branch auf origin."
    echo ""
    current_branch=$(git_cmd rev-parse --abbrev-ref HEAD)
    read -p "Branch für Reset [${current_branch}]: " target_branch
    target_branch=${target_branch:-$current_branch}
    echo -n "Wirklich Hard Reset auf origin/${target_branch} ausführen? [j/N]: "
    read -n 1 -r confirm
    echo
    if [[ ! $confirm =~ ^[Jj]$ ]]; then
        echo -e "${YELLOW}→ Abgebrochen${NC}"
        return
    fi
    git_cmd fetch --all --prune
    git_cmd reset --hard "origin/${target_branch}"
    git_cmd clean -fd
    echo -e "${GREEN}✓ Branch ${target_branch} auf origin gesetzt und Working Tree bereinigt${NC}"
    echo ""
    read -p "Drücke Enter zum Fortfahren..."
}

manage_stash() {
    while true; do
        echo ""
        echo "Stash-Management"
        echo ""
        echo "Gespeicherte Änderungen:"
        git_cmd stash list || echo "Keine stashed changes"
        echo ""
        echo "1) Änderungen speichern (stash)"
        echo "2) Gespeicherte Änderungen wiederherstellen (pop)"
        echo "3) Stash löschen"
        echo "4) Zurück"
        echo ""
        read -n 1 -p "Option [1-4]: " stash_opt
        echo

        case $stash_opt in
            1)
                read -p "Stash-Beschreibung (optional): " stash_msg
                if [ -n "$stash_msg" ]; then
                    git_cmd stash push -m "$stash_msg"
                else
                    git_cmd stash
                fi
                echo -e "${GREEN}Änderungen gespeichert (stash)${NC}"
                ;;
            2)
                echo "Stash-Liste:"
                git_cmd stash list | nl
                read -p "Stash-Index (neuester = 0): " stash_idx
                if [[ $stash_idx =~ ^[0-9]+$ ]]; then
                    git_cmd stash pop "stash@{$stash_idx}"
                    echo -e "${GREEN}Stash wiederhergestellt${NC}"
                fi
                ;;
            3)
                git_cmd stash list | nl
                read -p "Index löschen: " stash_idx
                if [[ $stash_idx =~ ^[0-9]+$ ]]; then
                    git_cmd stash drop "stash@{$stash_idx}"
                    echo -e "${GREEN}Stash gelöscht${NC}"
                fi
                ;;
            4) break ;;
        esac
    done
}

cleanup_branches() {
    echo ""
    echo "Cleanup"
    echo ""
    echo "Entferne gelöschte Remote-Branches..."
    git_cmd fetch --prune origin
    echo -e "${GREEN}Cleanup durchgeführt${NC}"
    echo ""
    read -p "Drücke Enter..."
}

# ============================================================
# 5) STATUS & INFO
# ============================================================

show_status() {
    echo ""
    echo "Repository-Status"
    echo ""
    echo "Aktueller Status:"
    git_cmd status
    echo ""
    echo "Alle Branches:"
    git_cmd branch -v
    echo ""
    echo "Neueste Tags:"
    git_cmd tag -l | sort -V | tail -10
    echo ""
    echo -e "${YELLOW}Neueste Commits:${NC}"
    git log --oneline -10
    echo ""
    read -p "Drücke Enter zum Fortfahren..."
}

# ============================================================
# MAIN LOOP
# ============================================================

check_git_repo

while true; do
    show_main_menu

    case $main_option in
        1) git_workflow ;;
        2) branch_management ;;
        3) branch_merging ;;
        4) tools_menu ;;
        5) show_status ;;
        6|q|Q)
            echo ""
            echo -e "${GREEN}👋 Auf Wiedersehen!${NC}"
            exit 0
            ;;
        *)
            echo -e "${RED}Ungültige Option!${NC}"
            sleep 1
            ;;
    esac
done
