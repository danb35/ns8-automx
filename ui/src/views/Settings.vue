<!--
  Copyright (C) 2026 Dan Brown
  SPDX-License-Identifier: GPL-3.0-or-later
-->
<template>
  <cv-grid fullWidth>
    <cv-row>
      <cv-column class="page-title">
        <h2>{{ $t("settings.title") }}</h2>
      </cv-column>
    </cv-row>
    <cv-row v-if="error.getConfiguration">
      <cv-column>
        <NsInlineNotification
          kind="error"
          :title="$t('action.get-configuration')"
          :description="error.getConfiguration"
          :showCloseButton="false"
        />
      </cv-column>
    </cv-row>
    <cv-row>
      <cv-column>
        <cv-tile light>
          <cv-form @submit.prevent="configureModule">
            <NsTextInput
              :label="$t('settings.service_host')"
              :helper-text="$t('settings.service_host_help')"
              placeholder="automx.example.org"
              v-model.trim="serviceHost"
              class="mg-bottom maxwidth"
              :invalid-message="
                fieldError(error.configureModule, 'service_host')
              "
              :disabled="loading.getConfiguration || loading.configureModule"
              ref="serviceHost"
            />
            <NsToggle
              value="http2https"
              :label="$t('settings.http_to_https')"
              v-model="isHttpToHttpsEnabled"
              :disabled="stillLoading"
              class="mg-bottom"
            >
              <template slot="text-left">{{
                $t("settings.disabled")
              }}</template>
              <template slot="text-right">{{
                $t("settings.enabled")
              }}</template>
            </NsToggle>
            <NsToggle
              value="displayNames"
              :label="$t('settings.display_names')"
              v-model="isDisplayNamesEnabled"
              :disabled="stillLoading"
              class="mg-bottom"
            >
              <template #tooltip>
                {{ $t("settings.display_names_tooltip") }}
              </template>
              <template slot="text-left">{{
                $t("settings.disabled")
              }}</template>
              <template slot="text-right">{{
                $t("settings.enabled")
              }}</template>
            </NsToggle>
            <NsInlineNotification
              kind="info"
              :title="$t('settings.display_names_notice_title')"
              :description="$t('settings.display_names_notice_description')"
              :showCloseButton="false"
              class="mg-bottom maxwidth"
            />
            <NsInlineNotification
              v-if="error.configureModule"
              kind="error"
              :title="$t('action.configure-module')"
              :description="errorText(error.configureModule)"
              :showCloseButton="false"
              class="mg-bottom"
            />
            <NsButton
              kind="primary"
              :icon="Save20"
              :loading="loading.configureModule"
              :disabled="loading.getConfiguration || loading.configureModule"
              >{{ $t("settings.save") }}</NsButton
            >
          </cv-form>
        </cv-tile>
      </cv-column>
    </cv-row>
  </cv-grid>
</template>

<script>
import { mapState } from "vuex";
import {
  QueryParamService,
  UtilService,
  IconService,
  PageTitleService,
} from "@nethserver/ns8-ui-lib";
import AutomxService from "../mixins/automx";

export default {
  name: "Settings",
  mixins: [
    AutomxService,
    IconService,
    UtilService,
    QueryParamService,
    PageTitleService,
  ],
  pageTitle() {
    return this.$t("settings.title") + " - " + this.appName;
  },
  data() {
    return {
      q: {
        page: "settings",
      },
      urlCheckInterval: null,
      serviceHost: "",
      isHttpToHttpsEnabled: true,
      isDisplayNamesEnabled: true,
      loading: {
        getConfiguration: false,
        configureModule: false,
      },
      error: {
        getConfiguration: "",
        configureModule: null,
      },
    };
  },
  computed: {
    ...mapState(["instanceName", "core", "appName"]),
    stillLoading() {
      return this.loading.getConfiguration || this.loading.configureModule;
    },
  },
  created() {
    this.getConfiguration();
  },
  beforeRouteEnter(to, from, next) {
    next((vm) => {
      vm.watchQueryData(vm);
      vm.urlCheckInterval = vm.initUrlBindingForApp(vm, vm.q.page);
    });
  },
  beforeRouteLeave(to, from, next) {
    clearInterval(this.urlCheckInterval);
    next();
  },
  methods: {
    async getConfiguration() {
      this.loading.getConfiguration = true;
      this.error.getConfiguration = "";
      try {
        const config = await this.callAction("get-configuration");
        this.serviceHost = config.service_host || "";
        this.isHttpToHttpsEnabled = config.http2https;
        this.isDisplayNamesEnabled = config.display_names;
      } catch (err) {
        this.error.getConfiguration = this.errorText(err);
      }
      this.loading.getConfiguration = false;
    },
    async configureModule() {
      this.loading.configureModule = true;
      this.error.configureModule = null;
      try {
        await this.callAction("configure-module", {
          data: {
            service_host: this.serviceHost || null,
            http2https: this.isHttpToHttpsEnabled,
            display_names: this.isDisplayNamesEnabled,
          },
          title: this.$t("settings.configuring"),
        });
      } catch (err) {
        this.error.configureModule = err;
      }
      this.loading.configureModule = false;
    },
  },
};
</script>

<style scoped lang="scss">
@import "../styles/carbon-utils";
.mg-bottom {
  margin-bottom: $spacing-06;
}

.maxwidth {
  max-width: 38rem;
}
</style>
