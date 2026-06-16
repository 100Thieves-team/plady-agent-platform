package io.plady._00thieveswikimcp.wiki.infrastructure

import io.plady._00thieveswikimcp.wiki.api.PendingChangeRecord

interface PendingChangeStore {
    fun save(record: PendingChangeRecord)
    fun find(pendingChangeId: String): PendingChangeRecord?
    fun list(): List<PendingChangeRecord>
}
