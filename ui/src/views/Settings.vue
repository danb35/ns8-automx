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
        <NsTile light>
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
            <NsToggle
              value="resolveAliases"
              :label="$t('settings.resolve_aliases')"
              v-model="isResolveAliasesEnabled"
              :disabled="stillLoading"
              class="mg-bottom"
            >
              <template #tooltip>
                {{ $t("settings.resolve_aliases_tooltip") }}
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
            <h4 class="mg-bottom">{{ $t("settings.groupware_title") }}</h4>
            <p class="mg-bottom maxwidth">
              {{ $t("settings.groupware_description") }}
            </p>
            <cv-select
              :label="$t('settings.dav_module')"
              v-model="davModule"
              :disabled="stillLoading"
              :invalid-message="fieldError(error.configureModule, 'dav_module')"
              class="mg-bottom maxwidth"
            >
              <cv-select-option value="">{{
                $t("settings.groupware_none")
              }}</cv-select-option>
              <cv-select-option
                v-for="g in davProviders"
                :key="g.module_id"
                :value="g.module_id"
                >{{ groupwareLabel(g) }}</cv-select-option
              >
            </cv-select>
            <cv-select
              :label="$t('settings.activesync_module')"
              v-model="activesyncModule"
              :disabled="stillLoading"
              :invalid-message="
                fieldError(error.configureModule, 'activesync_module')
              "
              class="mg-bottom maxwidth"
            >
              <cv-select-option value="">{{
                $t("settings.groupware_none")
              }}</cv-select-option>
              <cv-select-option
                v-for="g in activesyncProviders"
                :key="g.module_id"
                :value="g.module_id"
                >{{ groupwareLabel(g) }}</cv-select-option
              >
            </cv-select>
            <NsInlineNotification
              v-if="!loading.getConfiguration && !groupware.length"
              kind="info"
              :title="$t('settings.groupware_none_found_title')"
              :description="$t('settings.groupware_none_found_description')"
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
        </NsTile>
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
      isResolveAliasesEnabled: true,
      davModule: "",
      activesyncModule: "",
      groupware: [],
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
    davProviders() {
      return this.groupware.filter((g) => g.dav_url);
    },
    activesyncProviders() {
      return this.groupware.filter((g) => g.activesync_url);
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
    groupwareLabel(g) {
      return `${this.$t("settings.kind_" + g.kind)} (${g.module_id}, ${
        g.host
      })`;
    },
    async getConfiguration() {
      this.loading.getConfiguration = true;
      this.error.getConfiguration = "";
      try {
        const config = await this.callAction("get-configuration");
        this.serviceHost = config.service_host || "";
        this.isHttpToHttpsEnabled = config.http2https;
        this.isDisplayNamesEnabled = config.display_names;
        this.isResolveAliasesEnabled = config.resolve_aliases;
        this.davModule = config.dav_module || "";
        this.activesyncModule = config.activesync_module || "";
        this.groupware = config.groupware;
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
            resolve_aliases: this.isResolveAliasesEnabled,
            dav_module: this.davModule || null,
            activesync_module: this.activesyncModule || null,
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
