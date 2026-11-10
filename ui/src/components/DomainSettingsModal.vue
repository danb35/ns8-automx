<!--
  Copyright (C) 2026 Dan Brown
  SPDX-License-Identifier: GPL-3.0-or-later
-->
<template>
  <NsModal
    size="default"
    :visible="isShown"
    :isLoading="loading.load || loading.save"
    :primaryButtonDisabled="loading.load || loading.save || !!error.load"
    @modal-hidden="hide"
    @primary-click="save"
  >
    <template slot="title">{{
      $t("domain_settings.title", { domain: domain })
    }}</template>
    <template slot="content">
      <NsInlineNotification
        v-if="error.load"
        kind="error"
        :title="$t('action.get-configuration')"
        :description="error.load"
        :showCloseButton="false"
        class="mg-bottom-md"
      />
      <template v-else>
        <p class="mg-bottom-md">{{ $t("domain_settings.intro") }}</p>
        <cv-select
          :label="$t('settings.display_names')"
          v-model="displayNames"
          :disabled="busy"
          class="mg-bottom-md"
        >
          <cv-select-option value="default">{{
            defaultLabel(onOffLabel(defaults.display_names))
          }}</cv-select-option>
          <cv-select-option value="on">{{
            $t("settings.enabled")
          }}</cv-select-option>
          <cv-select-option value="off">{{
            $t("settings.disabled")
          }}</cv-select-option>
        </cv-select>
        <cv-select
          :label="$t('settings.resolve_aliases')"
          v-model="resolveAliases"
          :disabled="busy"
          class="mg-bottom-md"
        >
          <cv-select-option value="default">{{
            defaultLabel(onOffLabel(defaults.resolve_aliases))
          }}</cv-select-option>
          <cv-select-option value="on">{{
            $t("settings.enabled")
          }}</cv-select-option>
          <cv-select-option value="off">{{
            $t("settings.disabled")
          }}</cv-select-option>
        </cv-select>
        <cv-select
          :label="$t('settings.dav_module')"
          v-model="davModule"
          :disabled="busy"
          :invalid-message="fieldError(error.save, 'dav_module')"
          class="mg-bottom-md"
        >
          <cv-select-option value="default">{{
            defaultLabel(moduleLabel(defaults.dav_module))
          }}</cv-select-option>
          <cv-select-option value="none">{{
            $t("settings.groupware_none")
          }}</cv-select-option>
          <cv-select-option
            v-for="id in moduleChoices('dav_url', davModule)"
            :key="id"
            :value="id"
            >{{ moduleLabel(id) }}</cv-select-option
          >
        </cv-select>
        <cv-select
          :label="$t('settings.activesync_module')"
          v-model="activesyncModule"
          :disabled="busy"
          :invalid-message="fieldError(error.save, 'activesync_module')"
          class="mg-bottom-md"
        >
          <cv-select-option value="default">{{
            defaultLabel(moduleLabel(defaults.activesync_module))
          }}</cv-select-option>
          <cv-select-option value="none">{{
            $t("settings.groupware_none")
          }}</cv-select-option>
          <cv-select-option
            v-for="id in moduleChoices('activesync_url', activesyncModule)"
            :key="id"
            :value="id"
            >{{ moduleLabel(id) }}</cv-select-option
          >
        </cv-select>
        <NsInlineNotification
          v-if="error.save"
          kind="error"
          :title="$t('action.set-domain-settings')"
          :description="errorText(error.save)"
          :showCloseButton="false"
        />
      </template>
    </template>
    <template slot="secondary-button">{{ core.$t("common.cancel") }}</template>
    <template slot="primary-button">{{ $t("domain_settings.save") }}</template>
  </NsModal>
</template>

<script>
import { mapState } from "vuex";
import { IconService, UtilService } from "@nethserver/ns8-ui-lib";
import AutomxService from "../mixins/automx";

// The domain's overrides as select values: "default" for a setting the
// domain doesn't override, "on"/"off" for a boolean, "none" for a groupware
// setting overridden to null, else the module id.
function toChoice(overrides, key) {
  if (!(key in overrides)) {
    return "default";
  }
  const value = overrides[key];
  if (typeof value === "boolean") {
    return value ? "on" : "off";
  }
  return value === null ? "none" : value;
}

const CHOICE_VALUES = { on: true, off: false, none: null };

function fromChoice(choice) {
  return choice in CHOICE_VALUES ? CHOICE_VALUES[choice] : choice;
}

export default {
  name: "DomainSettingsModal",
  mixins: [AutomxService, IconService, UtilService],
  props: {
    isShown: { type: Boolean, default: false },
    domain: { type: String, default: "" },
    overrides: { type: Object, default: () => ({}) },
  },
  data() {
    return {
      defaults: {
        display_names: true,
        resolve_aliases: true,
        dav_module: null,
        activesync_module: null,
      },
      groupware: [],
      displayNames: "default",
      resolveAliases: "default",
      davModule: "default",
      activesyncModule: "default",
      loading: { load: false, save: false },
      error: { load: "", save: null },
    };
  },
  computed: {
    ...mapState(["core"]),
    busy() {
      return this.loading.load || this.loading.save;
    },
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
    defaultLabel(value) {
      return this.$t("domain_settings.default", { value });
    },
    onOffLabel(value) {
      return this.$t(value ? "settings.enabled" : "settings.disabled");
    },
    moduleLabel(id) {
      if (!id) {
        return this.$t("settings.groupware_none");
      }
      const g = this.groupware.find((x) => x.module_id === id);
      return g
        ? `${this.$t("settings.kind_" + g.kind)} (${g.module_id}, ${g.host})`
        : this.$t("domain_settings.not_available", { module: id });
    },
    moduleChoices(service, selected) {
      // The providers of this service, plus the stored choice if it no
      // longer is one, so the select doesn't silently show another value.
      const ids = this.groupware
        .filter((g) => g[service])
        .map((g) => g.module_id);
      if (
        !["default", "none"].includes(selected) &&
        !ids.includes(selected)
      ) {
        ids.push(selected);
      }
      return ids;
    },
    async load() {
      this.loading.load = true;
      this.error.load = "";
      this.error.save = null;
      try {
        const config = await this.callAction("get-configuration");
        this.defaults = {
          display_names: config.display_names,
          resolve_aliases: config.resolve_aliases,
          dav_module: config.dav_module,
          activesync_module: config.activesync_module,
        };
        // Options before values: Vue sets a <select>'s value before
        // patching its options, and the browser falls back to the first
        // option when the value has none yet (see Settings.vue).
        this.groupware = config.groupware;
        this.davModule = "default";
        this.activesyncModule = "default";
        await this.$nextTick();
        this.displayNames = toChoice(this.overrides, "display_names");
        this.resolveAliases = toChoice(this.overrides, "resolve_aliases");
        this.davModule = toChoice(this.overrides, "dav_module");
        this.activesyncModule = toChoice(this.overrides, "activesync_module");
      } catch (err) {
        this.error.load = this.errorText(err);
      }
      this.loading.load = false;
    },
    async save() {
      const overrides = {};
      for (const [key, choice] of [
        ["display_names", this.displayNames],
        ["resolve_aliases", this.resolveAliases],
        ["dav_module", this.davModule],
        ["activesync_module", this.activesyncModule],
      ]) {
        if (choice !== "default") {
          overrides[key] = fromChoice(choice);
        }
      }
      this.loading.save = true;
      this.error.save = null;
      try {
        await this.callAction("set-domain-settings", {
          data: { domain: this.domain, overrides },
        });
        this.$emit("changed");
        this.hide();
      } catch (err) {
        this.error.save = err;
      }
      this.loading.save = false;
    },
  },
};
</script>
