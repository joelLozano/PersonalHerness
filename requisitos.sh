#!/usr/bin/env bash
# Revisa e instala el software necesario para el harness (y tu proyecto). Ver: ./requisitos.sh --help
exec bash "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/agentes/requisitos.sh" "$@"
