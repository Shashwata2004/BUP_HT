"""Socket smoke-test fixture only. NEVER use this as the competition interpreter.

Returns no_op for synthetic unrelated notes. Not copied into the production image.
"""

import json

from fastapi import FastAPI

app = FastAPI()


@app.post("/v1/chat/completions")
async def complete(body: dict):
    notes = json.loads(body["messages"][1]["content"])["operator_notes"]
    directives = [
        {
            "note_index": i,
            "applies": False,
            "directive_type": "no_op",
            "structured_adjustment": None,
            "explanation": "Unrelated synthetic note.",
        }
        for i in range(len(notes))
    ]
    return {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"content": json.dumps({"directive_interpretation": directives})},
            }
        ]
    }
