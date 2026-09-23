<!--
  Copyright (C) 2026 Dan Brown
  SPDX-License-Identifier: GPL-3.0-or-later
-->
<template>
  <NsModal size="default" :visible="isShown" @modal-hidden="hide">
    <template slot="title">{{
      $t("profile_link.title", { domain: domain })
    }}</template>
    <template slot="content">
      <NsInlineNotification
        v-if="error.load"
        kind="error"
        :title="$t('action.get-profile-link')"
        :description="error.load"
        :showCloseButton="false"
        class="mg-bottom-md"
      />
      <template v-else>
        <p class="mg-bottom-md">{{ $t("profile_link.intro") }}</p>

        <p class="mg-bottom-sm">
          <strong>{{ $t("profile_link.url") }}</strong>
        </p>
        <NsCodeSnippet
          :copyTooltip="core.$t('common.copy_to_clipboard')"
          :copy-feedback="core.$t('common.copied_to_clipboard')"
          :wrap-text="true"
          hideExpandButton
          class="mg-bottom-md"
          >{{ url }}</NsCodeSnippet
        >

        <p class="mg-bottom-sm">
          <strong>{{ $t("profile_link.snippet_title") }}</strong>
        </p>
        <p class="mg-bottom-sm">{{ $t("profile_link.snippet_description") }}</p>
        <NsCodeSnippet
          :copyTooltip="core.$t('common.copy_to_clipboard')"
          :copy-feedback="core.$t('common.copied_to_clipboard')"
          :wrap-text="true"
          >{{ htmlSnippet }}</NsCodeSnippet
        >

        <NsInlineNotification
          kind="info"
          :title="$t('profile_link.no_auth_title')"
          :description="$t('profile_link.no_auth_description')"
          :showCloseButton="false"
          class="mg-top-md"
        />
      </template>
    </template>
    <template slot="secondary-button">{{ core.$t("common.close") }}</template>
  </NsModal>
</template>

<script>
import { mapState } from "vuex";
import { IconService, UtilService } from "@nethserver/ns8-ui-lib";
import AutomxService from "../mixins/automx";

export default {
  name: "ProfileLinkModal",
  mixins: [AutomxService, IconService, UtilService],
  props: {
    isShown: { type: Boolean, default: false },
    domain: { type: String, default: "" },
  },
  data() {
    return {
      url: "",
      htmlSnippet: "",
      loading: { load: false },
      error: { load: "" },
    };
  },
  computed: {
    ...mapState(["core"]),
  },
  watch: {
    isShown(shown) {
      if (shown) {
        this.load();
      }
    },
  },
  methods: {
    hide() {
      this.$emit("hide");
    },
    async load() {
      this.loading.load = true;
      this.error.load = "";
      try {
        const out = await this.callAction("get-profile-link", {
          data: { domain: this.domain },
        });
        this.url = out.url;
        this.htmlSnippet = out.html_snippet;
      } catch (err) {
        this.error.load = this.errorText(err);
      }
      this.loading.load = false;
    },
  },
};
</script>
