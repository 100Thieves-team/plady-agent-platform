package io.plady._00thieveswikimcp.wiki.application

import org.springframework.stereotype.Component

/** Default adapter used until the external Plady skill runtime is wired into this app. */
@Component
class UnavailableDraftSkillAdapter : DraftSkillAdapter {
    override val available: Boolean = false
}
