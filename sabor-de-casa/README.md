# Sabor de Casa – Cardápio

Sistema web para a marmitaria manter o cardápio organizado por categorias.
Entidades: **Categoria** e **Prato** (uma categoria reúne vários pratos; cada prato pertence a uma categoria).

## Como rodar localmente
Requer apenas Python 3 (sem instalar nada).

    python3 server.py --seed    # primeira vez: cria o banco com dados de exemplo
    python3 server.py           # nas próximas

Abra http://localhost:8000

## API
| Operação | Categoria | Prato |
|---|---|---|
| Listar | GET /api/categorias | GET /api/pratos?categoria_id=1 |
| Obter | GET /api/categorias/{id} | GET /api/pratos/{id} |
| Criar | POST /api/categorias | POST /api/pratos |
| Atualizar | PUT /api/categorias/{id} | PUT /api/pratos/{id} |
| Excluir | DELETE /api/categorias/{id} | DELETE /api/pratos/{id} |

## Regras validadas
Campos obrigatórios; preço maior que zero; nome de categoria sem repetição;
categoria com pratos não pode ser excluída.

## Armazenamento
SQLite (`cardapio.db`) com chave estrangeira entre prato e categoria.

## Online
Link: (cole aqui o endereço do Render)
Obs.: no plano gratuito o primeiro acesso pode levar cerca de 1 minuto e os dados voltam ao estado inicial quando o serviço reinicia.
