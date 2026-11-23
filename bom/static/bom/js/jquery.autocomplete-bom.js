(function ($) {
  "use strict";
  $.fn.autocomplete = function (options) {
    options = options || {};
    return this.each(function () {
      var $input = $(this);
      var data = options.data || {};
      var keys = Object.keys(data);
      var minLength = options.minLength == null ? 1 : options.minLength;
      var debounceMs = options.debounce == null ? 0 : options.debounce;
      var sourceUrl = options.source || null;
      var $list = $('<ul class="bom-autocomplete" role="listbox"></ul>');
      var debounceTimer = null;
      var requestSeq = 0;
      $input.css("position", "relative");
      $input.parent().css("position", "relative");
      $input.after($list);
      $list.hide();

      function close() {
        $list.hide().empty();
      }

      function render(matches) {
        if (options.limit) {
          matches = matches.slice(0, options.limit);
        }
        $list.empty();
        matches.forEach(function (item) {
          var label = typeof item === "string" ? item : item.label;
          var value = typeof item === "string" ? item : item.value;
          var $li = $('<li role="option"></li>').text(label);
          $li.on("mousedown", function (e) {
            e.preventDefault();
            if (typeof options.onAutocomplete === "function") {
              options.onAutocomplete(value);
            } else {
              $input.val(value);
            }
            close();
          });
          $list.append($li);
        });
        if (matches.length) {
          $list.show();
        } else {
          close();
        }
      }

      function localMatches(q) {
        var lower = q.toLowerCase();
        return keys.filter(function (k) {
          return k.toLowerCase().indexOf(lower) !== -1;
        });
      }

      function runSuggest(q) {
        if (sourceUrl) {
          var seq = ++requestSeq;
          $.getJSON(sourceUrl, { q: q, limit: options.limit })
            .done(function (resp) {
              if (seq !== requestSeq) {
                return;
              }
              var matches = (resp && resp.results) || [];
              render(matches);
            })
            .fail(function () {
              if (seq === requestSeq) {
                close();
              }
            });
          return;
        }
        render(localMatches(q));
      }

      $input.on("input", function () {
        var q = String($input.val() || "");
        requestSeq += 1;
        close();
        clearTimeout(debounceTimer);
        if (q.length < minLength) {
          return;
        }
        if (debounceMs > 0) {
          debounceTimer = setTimeout(function () {
            runSuggest(q);
          }, debounceMs);
        } else {
          runSuggest(q);
        }
      });

      $input.on("blur", function () {
        requestSeq += 1;
        clearTimeout(debounceTimer);
        setTimeout(close, 150);
      });
    });
  };

  $(function () {
    $("input[data-part-autocomplete]").each(function () {
      var input = this;
      $(input).autocomplete({
        source: input.getAttribute("data-part-autocomplete"),
        limit: Number(input.getAttribute("data-autocomplete-limit")),
        minLength: 1,
        debounce: 200,
        onAutocomplete: function (value) {
          $(input).val(value);
          if (input.getAttribute("data-autocomplete-submit") === "true") {
            input.form.submit();
          }
        },
      });
    });
  });
})(jQuery);
