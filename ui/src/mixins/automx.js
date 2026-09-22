//
// Copyright (C) 2026 Dan Brown
// SPDX-License-Identifier: GPL-3.0-or-later
//
// One promise-returning call for NS8 tasks, instead of manually registering
// three event listeners per call (the pattern AGENTS-frontend.md shows).
// Modeled on ns8-dnshelper's ui/src/mixins/dnshelper.js (same author, same
// house style) -- see that file for the fuller rationale in its comments.
//
//   const output = await this.callAction("get-domains");
//
// Rejects with { kind, errors, message }:
//   - kind "validation": the action refused the input; errors is the NS8
//     list of { field, parameter, value, error, message? }
//   - kind "aborted": the task failed
//   - kind "request": the task could not even be created (network, 401...)
// Use errorText(err) for a translated message, or fieldError(err, field)
// for one field's message next to its input.
import to from "await-to-js";
import { TaskService, UtilService } from "@nethserver/ns8-ui-lib";

export default {
  name: "AutomxService",
  mixins: [TaskService, UtilService],
  methods: {
    callAction(action, { data, moduleId, title } = {}) {
      return new Promise((resolve, reject) => {
        const eventId = this.getUuid();
        const root = this.$store.state.core.$root;
        const events = ["completed", "aborted", "validation-failed"].map(
          (name) => `${action}-${name}-${eventId}`
        );
        const done = () => events.forEach((e) => root.$off(e));

        root.$once(events[0], (taskContext, taskResult) => {
          done();
          resolve(taskResult.output);
        });
        root.$once(events[1], (taskResult) => {
          done();
          console.error(`${action} aborted`, taskResult);
          reject({ kind: "aborted", errors: [], message: "" });
        });
        root.$once(events[2], (validationErrors) => {
          done();
          reject({ kind: "validation", errors: validationErrors, message: "" });
        });

        const task = {
          action,
          extra: {
            title: title || this.$t("action." + action),
            isNotificationHidden: true,
            eventId,
          },
        };
        if (data !== undefined) {
          task.data = data;
        }
        to(
          this.createModuleTaskForApp(
            moduleId || this.$store.state.instanceName,
            task
          )
        ).then(([err]) => {
          if (err) {
            done();
            reject({
              kind: "request",
              errors: [],
              message: this.getErrorMessage(err),
            });
          }
        });
      });
    },

    /** A translated, human readable message for a rejection of callAction. */
    errorText(err) {
      if (err && err.kind === "validation" && err.errors.length) {
        return err.errors.map((e) => this.validationText(e)).join(" ");
      }
      if (err && err.kind === "request") {
        return err.message;
      }
      return this.$t("error.generic_error");
    },

    validationText(e) {
      const key = "dns_error." + e.error;
      const text = this.$te(key) ? this.$t(key) : e.error;
      if (!e.message) {
        return text;
      }
      // dnshelper's own message names exactly what was refused/why --
      // prefer it over the generic label when there's one to show.
      return `${text} (${e.message})`;
    },

    /** The first validation error for a field, or "" */
    fieldError(err, field) {
      if (!err || err.kind !== "validation") {
        return "";
      }
      const e = err.errors.find(
        (x) => x.parameter === field || x.field === field
      );
      return e ? this.validationText(e) : "";
    },
  },
};
