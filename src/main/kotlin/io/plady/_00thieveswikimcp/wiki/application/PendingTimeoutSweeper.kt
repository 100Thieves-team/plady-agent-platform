package io.plady._00thieveswikimcp.wiki.application

import org.slf4j.LoggerFactory
import org.springframework.scheduling.annotation.Scheduled
import org.springframework.stereotype.Component
import java.time.Instant

@Component
class PendingTimeoutSweeper(
    private val pendingService: PendingChangeService,
    private val workflowService: WikiWorkflowService,
) {
    private val log = LoggerFactory.getLogger(javaClass)

    @Scheduled(fixedDelayString = "\${plady.wiki.workflow.timeout-sweep-interval-millis:60000}")
    fun scheduledSweep() {
        sweepExpired()
    }

    fun sweepExpired(now: Instant = Instant.now()): Int {
        val expired = pendingService.pendingApprovals().filter { it.lockExpiresAt.isBefore(now) }
        expired.forEach { record ->
            val response = workflowService.abortPending(record.pendingChangeId, reason = "lock timeout")
            if (response.ok) {
                log.warn("Timed out pending change {} via background sweeper.", record.pendingChangeId)
            } else {
                log.error(
                    "Failed to timeout pending change {} via background sweeper: {}",
                    record.pendingChangeId,
                    response.error?.message,
                )
            }
        }
        return expired.size
    }
}
